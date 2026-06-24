"""
YouTube → Audio downloader
Залежності: pip install yt-dlp rich
Системна залежність: ffmpeg (brew install ffmpeg / apt install ffmpeg)
"""

"""
# Встановити залежності
pip install yt-dlp rich
brew install ffmpeg  # або apt install ffmpeg

# Запуск
python downloader.py                                    # інтерактивний режим
python downloader.py "https://youtube.com/watch?v=..."             # m4a (default)
python downloader.py "https://youtube.com/watch?v=..." mp3         # MP3 320kbps
python downloader.py "https://youtube.com/watch?v=..." flac ~/Music # FLAC у ~/Music

# Плейлист
python downloader.py "https://youtube.com/playlist?list=..."
"""

import sys
import subprocess
from pathlib import Path
from dataclasses import dataclass, field

import yt_dlp
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()


@dataclass
class DownloadConfig:
    url: str
    output_dir: Path = field(default_factory=lambda: Path.home() / "Downloads" / "audio")
    format: str = "bestaudio/best"
    audio_format: str = "m4a"
    audio_quality: str = "0"
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    write_subs: bool = False


def check_ffmpeg() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def build_ydl_opts(config: DownloadConfig) -> dict:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    postprocessors = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": config.audio_format,
            "preferredquality": config.audio_quality,
        },
        {"key": "FFmpegMetadata", "add_metadata": True},
    ]

    if config.embed_thumbnail:
        postprocessors.append({"key": "EmbedThumbnail"})

    return {
        "format": config.format,
        "outtmpl": str(config.output_dir / "%(uploader)s - %(title)s.%(ext)s"),
        "postprocessors": postprocessors,
        "writethumbnail": config.embed_thumbnail,
        "writesubtitles": config.write_subs,
        "quiet": True,
        "no_warnings": False,
        "ignoreerrors": False,
        "http_chunk_size": 10_485_760,
        "retries": 5,
        "fragment_retries": 5,
        #"cookiesfrombrowser": ("chrome",),   # або "firefox", "edge"
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }


class ProgressHook:

    def __init__(self):
        self._progress: Progress | None = None
        self._task_id = None
        self._total: int | None = None

    def set_progress(self, progress: Progress, task_id) -> None:
        self._progress = progress
        self._task_id = task_id

    def __call__(self, d: dict) -> None:
        if self._progress is None:
            return

        status = d.get("status")

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0

            if total and self._total != total:
                self._total = total
                self._progress.update(self._task_id, total=total)

            speed_str = f"{speed / 1024:.1f} KB/s" if speed else "?"
            eta_str = f"ETA: {eta}s" if eta else ""

            self._progress.update(
                self._task_id,
                completed=downloaded,
                description=f"[cyan]Завантаження[/] [dim]{speed_str} {eta_str}[/]",
            )

        elif status == "finished":
            self._progress.update(
                self._task_id,
                description="[green]Конвертація аудіо...[/]",
            )


def download(config: DownloadConfig) -> Path | None:
    hook = ProgressHook()
    opts = build_ydl_opts(config)
    opts["progress_hooks"] = [hook]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("[cyan]Ініціалізація...[/]", total=None)
        hook.set_progress(progress, task_id)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                progress.update(task_id, description="[yellow]Отримання метаданих...[/]")
                info = ydl.extract_info(config.url, download=False)

                if info is None:
                    console.print("[red]❌ Не вдалося отримати інформацію про відео[/]")
                    return None

                title = info.get("title", "Unknown")
                duration = info.get("duration", 0)
                uploader = info.get("uploader", "Unknown")

                console.print(Panel(
                    f"[bold]{title}[/]\n"
                    f"[dim]Автор:[/] {uploader}\n"
                    f"[dim]Тривалість:[/] {duration // 60}:{duration % 60:02d}",
                    title="[green]🎵 Відео знайдено[/]",
                    border_style="green",
                ))

                progress.update(task_id, description="[cyan]Завантаження...[/]")
                ydl.download([config.url])

                filename = ydl.prepare_filename(info)
                output_path = Path(filename).with_suffix(f".{config.audio_format}")

                progress.update(task_id, description="[green]✅ Готово![/]", completed=1, total=1)
                return output_path

        except yt_dlp.utils.DownloadError as e:
            console.print(f"[red]❌ Помилка завантаження:[/] {e}")
            return None
        except yt_dlp.utils.ExtractorError as e:
            console.print(f"[red]❌ Помилка екстракції:[/] {e}")
            return None


def interactive_mode() -> DownloadConfig:
    console.print(Panel(
        "[bold cyan]YouTube → Audio Downloader[/]\n[dim]Найкраща якість · yt-dlp + ffmpeg[/]",
        border_style="cyan",
    ))

    url = Prompt.ask("[yellow]URL відео або плейлисту[/]")

    fmt_choice = Prompt.ask(
        "[yellow]Формат аудіо[/]",
        choices=["m4a", "mp3", "opus", "flac"],
        default="m4a",
    )

    quality_note = {
        "m4a":  "копія оригінального AAC треку (без втрат якості)",
        "mp3":  "перекодування у 320kbps MP3",
        "opus": "копія opus треку (найкраща для стрімінгу)",
        "flac": "перекодування у lossless FLAC",
    }
    console.print(f"[dim]ℹ {quality_note[fmt_choice]}[/]")

    output_dir = Prompt.ask(
        "[yellow]Директорія збереження[/]",
        default=str(Path.home() / "Downloads" / "audio"),
    )

    embed_thumb = Confirm.ask("[yellow]Вбудувати обкладинку?[/]", default=True)

    return DownloadConfig(
        url=url,
        output_dir=Path(output_dir),
        audio_format=fmt_choice,
        audio_quality="0",  # завжди максимальна
        embed_thumbnail=embed_thumb,
    )


def main() -> int:
    if not check_ffmpeg():
        console.print(Panel(
            "[red]ffmpeg не знайдено![/]\n\n"
            "[yellow]Встановіть:[/]\n"
            "  macOS:  [cyan]brew install ffmpeg[/]\n"
            "  Ubuntu: [cyan]sudo apt install ffmpeg[/]\n"
            "  Windows:[cyan]winget install ffmpeg[/]",
            title="[red]❌ Залежність відсутня[/]",
            border_style="red",
        ))
        return 1

    if len(sys.argv) >= 2:
        url = sys.argv[1]
        fmt = sys.argv[2] if len(sys.argv) > 2 else "m4a"
        out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path.home() / "Downloads" / "audio"
        config = DownloadConfig(url=url, audio_format=fmt, output_dir=out)
    else:
        config = interactive_mode()

    result = download(config)

    if result:
        console.print(f"\n[green]✅ Збережено:[/] [bold]{config.output_dir}[/]")
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
