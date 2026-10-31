"""Captura de cliques, screenshots e anotação visual dos passos.

O módulo foi desenhado para rodar dentro do processo do Streamlit sem
bloquear a interface:

* o listener do ``pynput`` apenas enfileira o clique (operação rápida);
* uma thread trabalhadora faz o screenshot com ``mss``, desenha o marcador
  vermelho com ``Pillow`` e grava o PNG em disco.

Cada captura gera um :class:`Step` imutável, seguro para ser lido pela
interface a qualquer momento.
"""

from __future__ import annotations

import atexit
import ctypes
import logging
import os
import queue
import re
import sys
import threading
import time
import uuid
import weakref
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependências opcionais: a aplicação continua abrindo mesmo sem backend de
# captura (por exemplo, em um servidor Linux sem interface gráfica).
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depende do sistema operacional
    from pynput import keyboard as _pynput_keyboard
    from pynput import mouse as _pynput_mouse

    PYNPUT_AVAILABLE = True
    PYNPUT_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover
    _pynput_keyboard = None
    _pynput_mouse = None
    PYNPUT_AVAILABLE = False
    PYNPUT_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

try:  # pragma: no cover - depende do sistema operacional
    import mss

    MSS_AVAILABLE = True
    MSS_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover
    mss = None
    MSS_AVAILABLE = False
    MSS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

try:  # mss >= 10 renomeou a classe principal para MSS
    _MSS_CLASS = getattr(mss, "MSS", None) or getattr(mss, "mss", None)
except Exception:  # pragma: no cover
    _MSS_CLASS = None


BUTTON_LABELS: dict[str, str] = {
    "left": "Clique esquerdo",
    "right": "Clique direito",
    "middle": "Clique do meio",
    "x1": "Botão lateral 1",
    "x2": "Botão lateral 2",
}

DEFAULT_DESCRIPTION = "Clique no elemento destacado."

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
_DPI_READY = False
_DPI_LOCK = threading.Lock()

_ALL_RECORDERS: "weakref.WeakSet[ClickRecorder]" = weakref.WeakSet()
_ALL_LOCK = threading.Lock()


class RecorderError(RuntimeError):
    """Erro amigável de configuração ou de captura de tela."""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def backend_status() -> tuple[bool, str]:
    """Retorna ``(disponivel, mensagem)`` sobre o backend de captura."""
    problems: list[str] = []
    if not PYNPUT_AVAILABLE:
        problems.append(
            "pynput indisponível"
            + (f" ({PYNPUT_IMPORT_ERROR})" if PYNPUT_IMPORT_ERROR else "")
        )
    if not MSS_AVAILABLE:
        problems.append(
            "mss indisponível" + (f" ({MSS_IMPORT_ERROR})" if MSS_IMPORT_ERROR else "")
        )
    if not problems:
        return True, "Backend de captura pronto."
    return (
        False,
        "A gravação de cliques não está disponível neste ambiente: "
        + "; ".join(problems)
        + ". Em Linux, use uma sessão X11 (Wayland não é suportado pelo pynput).",
    )


def button_label(button: str) -> str:
    """Rótulo em português para o botão do mouse."""
    return BUTTON_LABELS.get((button or "").lower(), f"Botão {button}")


def _hex_to_rgb(value: str, fallback: tuple[int, int, int] = (229, 57, 53)):
    match = _HEX_RE.match((value or "").strip())
    if not match:
        return fallback
    raw = match.group(1)
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _enable_dpi_awareness() -> None:
    """Alinha as coordenadas do pynput e as dimensões do mss em telas com DPI.

    No Windows, sem isso, processos sem consciência de DPI recebem
    coordenadas "virtualizadas" enquanto o screenshot é físico (ou vice-versa).
    """
    global _DPI_READY
    if _DPI_READY or sys.platform != "win32":
        return
    with _DPI_LOCK:
        if _DPI_READY:
            return
        try:
            # PROCESS_PER_MONITOR_DPI_AWARE_V2
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            _DPI_READY = True
            return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _DPI_READY = True
            return
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            logger.debug("Não foi possível habilitar DPI awareness.", exc_info=True)
        _DPI_READY = True


def _auto_coordinate_scale() -> float:
    """Fator entre coordenadas do mouse e pixels da imagem (macOS Retina).

    No Windows e no Linux o fator é 1. Em macOS com tela Retina, o pynput
    trabalha em pontos e o screenshot em pixels. A variável de ambiente
    ``MANUAL_COORD_SCALE`` permite sobrescrever a detecção automática.
    """
    override = os.environ.get("MANUAL_COORD_SCALE")
    if override:
        try:
            value = float(override)
            if value > 0:
                return value
        except ValueError:
            logger.warning("MANUAL_COORD_SCALE inválido: %r", override)

    if sys.platform != "darwin":
        return 1.0

    try:  # pragma: no cover - executado apenas em macOS
        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )

        class CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class CGRect(ctypes.Structure):
            _fields_ = [("origin", CGPoint), ("size", CGSize)]

        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
        cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        cg.CGDisplayBounds.restype = CGRect

        display = cg.CGMainDisplayID()
        pixels = float(cg.CGDisplayPixelsWide(display))
        points = float(cg.CGDisplayBounds(display).size.width)
        if pixels > 0 and points > 0:
            return max(1.0, round(pixels / points, 3))
    except Exception:
        logger.debug("Detecção de escala do macOS indisponível.", exc_info=True)
    return 1.0


def draw_click_indicator(
    image: Image.Image,
    x: int,
    y: int,
    *,
    radius: int = 26,
    color: str = "#E53935",
) -> Image.Image:
    """Desenha um círculo vermelho exatamente centrado em ``(x, y)``.

    O marcador é criado em alta resolução em um patch pequeno e reduzido com
    antialiasing, evitando alocar uma camada gigante para telas 4K.
    """
    rgb = _hex_to_rgb(color)
    radius = max(10, min(int(radius), 80))
    size = radius * 2 + 12
    scale = 4
    hi_size = size * scale
    center = hi_size // 2

    patch = Image.new("RGBA", (hi_size, hi_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(patch)

    outer = radius * scale
    draw.ellipse(
        (center - outer, center - outer, center + outer, center + outer),
        fill=(*rgb, 45),
        outline=(255, 255, 255, 245),
        width=max(2, 6 * scale),
    )
    inner = (radius - 6) * scale
    if inner > 4:
        draw.ellipse(
            (center - inner, center - inner, center + inner, center + inner),
            outline=(*rgb, 255),
            width=max(2, 4 * scale),
        )
    dot = max(2, 2 * scale)
    draw.ellipse(
        (center - dot, center - dot, center + dot, center + dot),
        fill=(255, 255, 255, 255),
    )

    patch = patch.resize((size, size), Image.LANCZOS)
    base = image.convert("RGBA")
    base.paste(patch, (x - size // 2, y - size // 2), patch)
    return base.convert("RGB")


def _looks_blank(image: Image.Image) -> bool:
    """Heurística para detectar screenshots pretos (permissão ausente)."""
    try:
        grayscale = image.convert("L")
        grayscale.thumbnail((64, 64))
        low, high = grayscale.getextrema()
        return high <= 12 and (high - low) <= 4
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Step:
    """Um passo capturado, imutável e seguro para leitura concorrente."""

    uid: str
    number: int
    captured_at: datetime
    x: int
    y: int
    button: str
    image_path: str
    image_width: int
    image_height: int
    monitor: int = 0
    annotated: bool = True
    description: str = DEFAULT_DESCRIPTION

    @property
    def time_label(self) -> str:
        return self.captured_at.strftime("%H:%M:%S")

    @property
    def button_label(self) -> str:
        return button_label(self.button)


@dataclass(frozen=True, slots=True)
class ClickEvent:
    x: int
    y: int
    button: str
    timestamp: float


# ---------------------------------------------------------------------------
# Gravador
# ---------------------------------------------------------------------------
class ClickRecorder:
    """Grava cliques do mouse e gera screenshots anotados.

    O objeto pode ser criado uma única vez por sessão do Streamlit e
    iniciado/parado várias vezes: os passos anteriores são preservados.
    """

    def __init__(
        self,
        output_dir: str | Path,
        *,
        capture_delay: float = 0.15,
        max_width: int | None = 1920,
        only_left_click: bool = False,
        enable_hotkeys: bool = True,
        indicator_color: str = "#E53935",
        indicator_radius: int = 26,
        coordinate_scale: float | None = None,
        on_capture: Callable[[Step], None] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.capture_delay = 0.15
        self.max_width: int | None = 1920
        self.only_left_click = False
        self.enable_hotkeys = True
        self.indicator_color = "#E53935"
        self.indicator_radius = 26
        self.coordinate_scale = coordinate_scale
        self.on_capture = on_capture

        self._lock = threading.RLock()
        self._steps: list[Step] = []
        self._queue: queue.Queue[ClickEvent | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._mouse_listener = None
        self._hotkey_listener = None
        self._running = False
        self._paused = False
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._paused_total = 0.0
        self._paused_since: float | None = None
        self._last_error: str | None = None
        self._last_warning: str | None = None
        self._stop_reason: str | None = None
        self._hotkeys_active = False
        self._run_id = 0
        self._coord_scale = 1.0

        self.configure(
            capture_delay=capture_delay,
            max_width=max_width,
            only_left_click=only_left_click,
            enable_hotkeys=enable_hotkeys,
            indicator_color=indicator_color,
            indicator_radius=indicator_radius,
            coordinate_scale=coordinate_scale,
        )

        with _ALL_LOCK:
            _ALL_RECORDERS.add(self)

    # ------------------------------------------------------------------
    # Configuração e estado
    # ------------------------------------------------------------------
    def configure(
        self,
        *,
        capture_delay: float | None = None,
        max_width: int | None = None,
        only_left_click: bool | None = None,
        enable_hotkeys: bool | None = None,
        indicator_color: str | None = None,
        indicator_radius: int | None = None,
        coordinate_scale: float | None = None,
    ) -> None:
        """Atualiza parâmetros. Só é permitido com a gravação parada."""
        with self._lock:
            if self._running:
                raise RecorderError(
                    "Pare a gravação antes de alterar as configurações de captura."
                )
            if capture_delay is not None:
                self.capture_delay = max(0.0, min(float(capture_delay), 5.0))
            if max_width is not None:
                self.max_width = None if max_width <= 0 else max(320, int(max_width))
            if only_left_click is not None:
                self.only_left_click = bool(only_left_click)
            if enable_hotkeys is not None:
                self.enable_hotkeys = bool(enable_hotkeys)
            if indicator_color is not None:
                self.indicator_color = indicator_color
            if indicator_radius is not None:
                self.indicator_radius = max(10, min(int(indicator_radius), 80))
            if coordinate_scale is not None:
                self.coordinate_scale = float(coordinate_scale)

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._running and self._paused

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._steps)

    @property
    def steps(self) -> tuple[Step, ...]:
        with self._lock:
            return tuple(self._steps)

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @property
    def last_warning(self) -> str | None:
        with self._lock:
            return self._last_warning

    @property
    def stop_reason(self) -> str | None:
        with self._lock:
            return self._stop_reason

    @property
    def hotkeys_active(self) -> bool:
        with self._lock:
            return self._hotkeys_active

    @property
    def elapsed_seconds(self) -> float:
        """Tempo de captura, descontando o período em pausa."""
        with self._lock:
            if self._started_at is None:
                return 0.0
            end = time.time() if self._running else (self._stopped_at or time.time())
            paused = self._paused_total
            if self._paused_since is not None and self._running:
                paused += max(0.0, time.time() - self._paused_since)
            return max(0.0, end - self._started_at - paused)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Inicia o listener e a thread de captura."""
        available, message = backend_status()
        if not available:
            raise RecorderError(message)

        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False
            self._paused_total = 0.0
            self._paused_since = None
            self._started_at = time.time()
            self._stopped_at = None
            self._stop_reason = None
            self._last_error = None
            self._last_warning = None
            self._hotkeys_active = False
            self._run_id += 1
            run_id = self._run_id
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._queue = queue.Queue()

        _enable_dpi_awareness()
        self._coord_scale = (
            float(self.coordinate_scale)
            if self.coordinate_scale is not None
            else _auto_coordinate_scale()
        )

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            with self._lock:
                self._running = False
            raise RecorderError(
                f"Não foi possível criar a pasta de capturas '{self.output_dir}': {exc}"
            ) from exc

        worker = threading.Thread(
            target=self._worker_loop,
            args=(self._queue, stop_event, run_id),
            name="manual-capture-worker",
            daemon=True,
        )
        self._worker = worker
        worker.start()

        try:
            listener = _pynput_mouse.Listener(on_click=self._on_click)
            listener.start()
            self._mouse_listener = listener
        except Exception as exc:
            self._cleanup_failed_start(stop_event)
            raise RecorderError(
                "Não foi possível iniciar o listener do mouse. "
                "No macOS, autorize o Acesso de Monitoramento de Entrada "
                "(Acessibilidade) para o terminal/Python."
            ) from exc

        if self.enable_hotkeys:
            try:
                hotkeys = _pynput_keyboard.GlobalHotKeys(
                    {
                        "<f8>": self._on_hotkey_pause,
                        "<f9>": self._on_hotkey_stop,
                    }
                )
                hotkeys.start()
                self._hotkey_listener = hotkeys
                self._hotkeys_active = True
            except Exception as exc:
                self._hotkeys_active = False
                self._last_warning = (
                    "Os atalhos F8/F9 não puderam ser ativados "
                    f"({type(exc).__name__}: {exc}). Use os botões da interface."
                )
                logger.warning("Falha ao registrar atalhos globais: %s", exc)

    def _cleanup_failed_start(self, stop_event: threading.Event) -> None:
        stop_event.set()
        with self._lock:
            self._running = False
            self._stopped_at = time.time()
            listener = self._mouse_listener
            self._mouse_listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        worker = self._worker
        if worker is not None:
            try:
                self._queue.put_nowait(None)
            except Exception:
                pass
            worker.join(timeout=2.0)
            self._worker = None

    def stop(
        self,
        *,
        discard_recent_seconds: float = 0.0,
        reason: str = "manual",
    ) -> None:
        """Para a gravação.

        ``discard_recent_seconds`` remove a última captura se ela tiver sido
        feita há menos de N segundos. Útil para descartar o clique no próprio
        botão "Parar" da interface.
        """
        with self._lock:
            was_running = self._running
            self._running = False
            self._stop_reason = reason
            self._stopped_at = time.time()
            if self._paused_since is not None:
                self._paused_total += max(0.0, self._stopped_at - self._paused_since)
                self._paused_since = None
            self._paused = False
            stop_event = self._stop_event
            stop_event.set()
            mouse_listener = self._mouse_listener
            hotkey_listener = self._hotkey_listener
            self._mouse_listener = None
            self._hotkey_listener = None
            self._hotkeys_active = False
            work_queue = self._queue
            worker = self._worker

        if mouse_listener is not None:
            try:
                mouse_listener.stop()
            except Exception:
                logger.debug("Falha ao parar listener do mouse.", exc_info=True)
        if hotkey_listener is not None:
            try:
                hotkey_listener.stop()
            except Exception:
                logger.debug("Falha ao parar atalhos globais.", exc_info=True)

        if worker is not None:
            try:
                work_queue.put_nowait(None)
            except Exception:
                pass
            worker.join(timeout=5.0)
            if worker.is_alive():
                logger.warning("Thread de captura ainda ativa após o timeout de parada.")
            self._worker = None

        # Descarta eventos que chegaram depois da parada.
        while True:
            try:
                work_queue.get_nowait()
            except queue.Empty:
                break
            else:
                work_queue.task_done()

        if discard_recent_seconds > 0:
            cutoff = time.time() - discard_recent_seconds
            with self._lock:
                removed = None
                if self._steps and self._steps[-1].captured_at.timestamp() >= cutoff:
                    removed = self._steps.pop()
            if removed is not None:
                self._remove_file(removed.image_path)

        if was_running:
            logger.info("Gravação encerrada (%s).", reason)

    def toggle_pause(self) -> bool:
        """Alterna pausa/retomada. Retorna o novo estado de pausa."""
        with self._lock:
            if not self._running:
                return False
            self._paused = not self._paused
            if self._paused:
                self._paused_since = time.time()
            else:
                if self._paused_since is not None:
                    self._paused_total += max(0.0, time.time() - self._paused_since)
                self._paused_since = None
            return self._paused

    def clear(self) -> None:
        """Remove todas as capturas da sessão (arquivos e registros)."""
        self.stop(reason="clear")
        with self._lock:
            steps = list(self._steps)
            self._steps.clear()
            self._started_at = None
            self._stopped_at = None
            self._paused_total = 0.0
            self._paused_since = None
            self._last_error = None
            self._last_warning = None
            self._stop_reason = None
        for step in steps:
            self._remove_file(step.image_path)
        try:
            for leftover in self.output_dir.glob("*.part"):
                self._remove_file(str(leftover))
        except OSError:
            logger.debug("Falha ao limpar arquivos temporários.", exc_info=True)

    # ------------------------------------------------------------------
    # Captura
    # ------------------------------------------------------------------
    def _on_click(self, x, y, button, pressed) -> None:  # pragma: no cover
        """Callback do pynput: apenas enfileira (não captura)."""
        if not pressed:
            return
        with self._lock:
            if not self._running or self._paused:
                return
            only_left = self.only_left_click
        if only_left:
            left = getattr(_pynput_mouse, "Button", None)
            if left is not None and button != left.left:
                return
        name = getattr(button, "name", "left")
        try:
            self._queue.put_nowait(
                ClickEvent(int(round(x)), int(round(y)), str(name), time.time())
            )
        except Exception:
            logger.debug("Falha ao enfileirar clique.", exc_info=True)

    def _worker_loop(
        self,
        work_queue: "queue.Queue[ClickEvent | None]",
        stop_event: threading.Event,
        run_id: int,
    ) -> None:
        while True:
            try:
                event = work_queue.get(timeout=0.2)
            except queue.Empty:
                if stop_event.is_set():
                    break
                continue

            try:
                if event is None:
                    break
                if stop_event.is_set():
                    break
                if self.paused:
                    continue
                if self.capture_delay:
                    time.sleep(self.capture_delay)
                if stop_event.is_set() or self.paused:
                    continue
                if run_id != self._run_id:
                    break
                self.capture_at(
                    event.x,
                    event.y,
                    event.button,
                    timestamp=event.timestamp,
                )
            except Exception as exc:
                logger.exception("Falha ao processar captura de clique.")
                with self._lock:
                    self._last_error = (
                        "Não foi possível capturar um clique. "
                        f"Detalhe: {type(exc).__name__}: {exc}"
                    )
            finally:
                work_queue.task_done()

    def capture_at(
        self,
        x: int,
        y: int,
        button: str = "left",
        *,
        timestamp: float | None = None,
    ) -> Step:
        """Captura a tela no ponto ``(x, y)`` e salva um PNG anotado.

        Público para permitir capturas avulsas/testes; o fluxo normal passa
        pela fila processada na thread trabalhadora.
        """
        if _MSS_CLASS is None:
            raise RecorderError("mss não está disponível para capturar a tela.")

        ts = time.time() if timestamp is None else float(timestamp)
        captured_at = datetime.fromtimestamp(ts)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            with _MSS_CLASS() as sct:  # type: ignore[union-attr]
                monitors = list(sct.monitors)
                target = monitors[0]
                monitor_number = 0
                for index, monitor in enumerate(monitors[1:], start=1):
                    if (
                        monitor["left"] <= x < monitor["left"] + monitor["width"]
                        and monitor["top"] <= y < monitor["top"] + monitor["height"]
                    ):
                        target = monitor
                        monitor_number = index
                        break
                shot = sct.grab(target)
                image = Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as exc:
            raise RecorderError(
                "Falha ao capturar a tela. Verifique as permissões de gravação "
                f"de tela do sistema. Detalhe: {type(exc).__name__}: {exc}"
            ) from exc

        blank = _looks_blank(image)
        if blank:
            with self._lock:
                self._last_warning = (
                    "A captura saiu totalmente preta. No macOS, autorize "
                    "'Gravação de Tela' em Preferências do Sistema > Privacidade "
                    "e Segurança e reinicie o terminal."
                )

        scale = 1.0
        if self.max_width and image.width > self.max_width:
            scale = self.max_width / float(image.width)
            resized_height = max(1, int(round(image.height * scale)))
            image = image.resize((self.max_width, resized_height), Image.LANCZOS)

        rel_x = int(round((x - int(target["left"])) * self._coord_scale * scale))
        rel_y = int(round((y - int(target["top"])) * self._coord_scale * scale))
        annotated = 0 <= rel_x < image.width and 0 <= rel_y < image.height
        if annotated:
            image = draw_click_indicator(
                image,
                rel_x,
                rel_y,
                radius=self.indicator_radius,
                color=self.indicator_color,
            )
        else:
            with self._lock:
                self._last_warning = (
                    "O clique ficou fora dos limites da captura; o marcador não "
                    "pôde ser desenhado."
                )

        with self._lock:
            number = len(self._steps) + 1
        stamp = captured_at.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = (
            f"passo_{number:03d}_{stamp}_{uuid.uuid4().hex[:6]}.png"
        )
        image_path = self.output_dir / filename
        temp_path = image_path.with_name(image_path.name + ".part")

        try:
            image.save(temp_path, format="PNG", compress_level=6)
            os.replace(temp_path, image_path)
        except Exception as exc:
            self._remove_file(str(temp_path))
            raise RecorderError(
                f"Falha ao salvar a captura em '{image_path}': {exc}"
            ) from exc

        step = Step(
            uid=uuid.uuid4().hex,
            number=number,
            captured_at=captured_at,
            x=int(x),
            y=int(y),
            button=str(button),
            image_path=str(image_path.resolve()),
            image_width=image.width,
            image_height=image.height,
            monitor=monitor_number,
            annotated=annotated,
            description=(
                DEFAULT_DESCRIPTION
                if button == "left"
                else f"{button_label(str(button))} no elemento destacado."
            ),
        )
        with self._lock:
            self._steps.append(step)
            self._last_error = None

        if self.on_capture is not None:
            try:
                self.on_capture(step)
            except Exception:
                logger.debug("Callback on_capture falhou.", exc_info=True)
        return step

    # ------------------------------------------------------------------
    # Atalhos/limpeza
    # ------------------------------------------------------------------
    def _on_hotkey_pause(self) -> None:  # pragma: no cover
        self.toggle_pause()

    def _on_hotkey_stop(self) -> None:  # pragma: no cover
        # Evita parar o listener de teclado de dentro do próprio callback.
        threading.Thread(
            target=self.stop,
            kwargs={"reason": "hotkey"},
            name="manual-capture-hotkey-stop",
            daemon=True,
        ).start()

    @staticmethod
    def _remove_file(path: str) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Não foi possível remover a captura %s", path)

    def __del__(self):  # pragma: no cover - defensivo
        try:
            if getattr(self, "_running", False):
                self.stop(reason="shutdown")
        except Exception:
            pass


def _stop_all_recorders() -> None:  # pragma: no cover - executado no shutdown
    with _ALL_LOCK:
        recorders = list(_ALL_RECORDERS)
    for recorder in recorders:
        try:
            recorder.stop(reason="shutdown")
        except Exception:
            pass


atexit.register(_stop_all_recorders)
