"""Interface Streamlit do Gerador Automático de Manuais e Procedimentos."""

from __future__ import annotations

import hashlib
import html
import io
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image

from exporter import (
    ManualConfig,
    ManualStep,
    build_manual,
    default_filename,
    normalize_hex,
)
from recorder import (
    ClickRecorder,
    RecorderError,
    backend_status,
)

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage" / "captures"
MAX_LOGO_BYTES = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Configuração da página e identidade visual
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Gerador de Manuais",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_CSS = """
<style>
:root {
    --brand: #1F4E79;
    --ink: #17212F;
    --muted: #667085;
    --line: #E3E9F2;
    --surface: #F6F8FC;
    --danger: #B42318;
    --success: #067647;
}
html, body, .stApp {
    font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
}
[data-testid="stHeader"] { background: rgba(255, 255, 255, .82); backdrop-filter: blur(8px); }
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #F8FAFD 0%, #F1F5FA 100%);
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1.1rem; }
.block-container { padding-top: 2.1rem; padding-bottom: 3rem; max-width: 1320px; }
#MainMenu, footer, [data-testid="stAppDeployButton"] { visibility: hidden; }
h1, h2, h3 { color: var(--ink); letter-spacing: -0.015em; }

.brand { display: flex; align-items: center; gap: 11px; padding: 4px 0 18px 0; }
.brand-mark {
    width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
    background: var(--brand); color: white; font-size: 20px;
    box-shadow: 0 6px 16px rgba(31, 78, 121, .22);
}
.brand-name { font-weight: 700; font-size: 1rem; line-height: 1.2; color: var(--ink); }
.brand-sub { font-size: .72rem; color: var(--muted); margin-top: 2px; }
.side-label {
    font-size: .68rem; letter-spacing: .14em; font-weight: 700;
    color: #8290A3; text-transform: uppercase; margin: 6px 0 8px 0;
}

.hero {
    position: relative; overflow: hidden;
    border: 1px solid var(--line); border-radius: 22px;
    padding: 30px 34px 28px 34px;
    background:
        radial-gradient(900px 240px at 90% -20%, rgba(31, 78, 121, .10), transparent 60%),
        linear-gradient(135deg, #FFFFFF 0%, #F5F8FC 100%);
    margin-bottom: 18px;
}
.hero-kicker {
    color: var(--brand); font-size: .7rem; font-weight: 700;
    letter-spacing: .2em; text-transform: uppercase; margin-bottom: 8px;
}
.hero h1 { font-size: clamp(1.75rem, 3vw, 2.4rem); line-height: 1.12; margin: 0 0 8px 0; font-weight: 700; }
.hero p { color: var(--muted); margin: 0; max-width: 780px; font-size: .98rem; line-height: 1.5; }
.hero-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.hero-chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: #FFFFFF; border: 1px solid var(--line); border-radius: 999px;
    padding: 5px 11px; font-size: .74rem; font-weight: 600; color: #44546A;
}
.hero-chip.brand { color: var(--brand); border-color: rgba(31, 78, 121, .22); background: rgba(31, 78, 121, .05); }

.status-pill {
    display: inline-flex; align-items: center; gap: 8px;
    border-radius: 999px; padding: 7px 13px;
    font-size: .8rem; font-weight: 700; line-height: 1;
    border: 1px solid var(--line); background: #FFFFFF; color: #44546A;
    white-space: nowrap;
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; display: inline-block; }
.status-pill.recording { color: var(--danger); background: #FEF3F2; border-color: #FECDCA; }
.status-pill.recording .status-dot { animation: pulse 1.25s ease-in-out infinite; }
.status-pill.paused { color: #9A5B00; background: #FFFAEB; border-color: #FEDF89; }
.status-pill.idle { color: #475467; background: #F8FAFC; }
@keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: .3; transform: scale(1.45); }
}

.live-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 2px 0 10px 0; }
.live-hint { color: var(--muted); font-size: .82rem; }
.rec-banner {
    border: 1px solid #FECDCA; background: #FFF8F7; color: #7A271A;
    padding: 11px 15px; border-radius: 12px; font-size: .86rem; margin: 8px 0 4px 0;
}
.rec-banner.paused { border-color: #FEDF89; background: #FFFCF5; color: #7A4E00; }
.rec-banner strong { font-weight: 700; }
.rec-keys {
    display: inline-block; margin-left: 8px; padding: 1px 7px; border-radius: 6px;
    background: rgba(122, 39, 26, .07); font-size: .75rem; font-weight: 700;
}

.step-badge {
    display: inline-block; background: var(--brand); color: #FFFFFF;
    border-radius: 8px; padding: 5px 10px; font-size: .7rem;
    font-weight: 800; letter-spacing: .09em; text-transform: uppercase;
    white-space: nowrap;
}
.step-badge.muted { background: #EAECF0; color: #667085; }
.step-context { color: var(--muted); font-size: .75rem; margin-left: 10px; }

.guide-card {
    border: 1px solid var(--line); border-radius: 16px; padding: 18px 18px 14px 18px;
    background: #FFFFFF; min-height: 145px;
}
.guide-num {
    width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center;
    background: rgba(31, 78, 121, .08); color: var(--brand);
    font-weight: 800; font-size: .8rem; margin-bottom: 10px;
}
.guide-card b { font-size: .92rem; }
.guide-card p { color: var(--muted); font-size: .8rem; line-height: 1.45; margin: 5px 0 0 0; }

/* Métricas um pouco mais leves */
[data-testid="stMetric"] {
    background: #FFFFFF; border: 1px solid var(--line); border-radius: 14px;
    padding: 14px 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, .03);
}
[data-testid="stMetricValue"] { font-size: 1.65rem; }
[data-testid="stMetricLabel"] { color: var(--muted); }

.stButton > button, .stDownloadButton > button { border-radius: 10px; font-weight: 600; }
[data-testid="stFileUploaderDropzone"] { border-radius: 12px; }
[data-testid="stExpander"] { border-radius: 12px; }
</style>
"""
st.markdown(BASE_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------------
DEFAULT_STATE: dict[str, object] = {
    "doc_title": "Manual de Procedimentos",
    "doc_company": "",
    "doc_subtitle": "",
    "doc_author": "",
    "doc_accent": "#1F4E79",
    "doc_include_meta": False,
    "doc_page_break": False,
    "start_delay": 3,
    "capture_delay": 0.15,
    "max_width": "1920",
    "only_left": True,
    "enable_hotkeys": True,
    "logo_bytes": None,
    "logo_name": "",
    "logo_nonce": 0,
    "step_meta": {},
    "rendered_count": 0,
    "last_running": False,
    "confirm_clear": False,
    "recorder_error": None,
    "doc_bytes": None,
    "doc_fingerprint": None,
    "doc_filename": None,
    "doc_generated_at": None,
}


def _init_state() -> None:
    for key, value in DEFAULT_STATE.items():
        st.session_state.setdefault(key, value)

    if "session_id" not in st.session_state:
        session_id = uuid.uuid4().hex[:10]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.session_state.session_id = session_id
        st.session_state.capture_dir = str(
            STORAGE_DIR / f"{stamp}_{session_id}"
        )

    if "recorder" not in st.session_state:
        st.session_state.recorder = ClickRecorder(
            st.session_state.capture_dir,
            capture_delay=float(st.session_state.capture_delay),
            max_width=_max_width_value(),
            only_left_click=bool(st.session_state.only_left),
            enable_hotkeys=bool(st.session_state.enable_hotkeys),
        )


def _max_width_value() -> int:
    """0 significa "sem redimensionamento" para o gravador."""
    raw = st.session_state.get("max_width", "1920")
    if raw == "Original":
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1920


def _recorder() -> ClickRecorder:
    return st.session_state.recorder


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _accent() -> str:
    return normalize_hex(st.session_state.get("doc_accent", "#1F4E79"))


# ---------------------------------------------------------------------------
# Sincronização dos passos
# ---------------------------------------------------------------------------
def _seed_widget_state(uid: str, meta: dict) -> None:
    for prefix, value in (
        ("desc", meta.get("description", "")),
        ("notes", meta.get("notes", "")),
        ("inc", bool(meta.get("include", True))),
    ):
        key = f"{prefix}_{uid}"
        if key not in st.session_state:
            st.session_state[key] = value


def _sync_steps(rec: ClickRecorder) -> list:
    steps = list(rec.steps)
    meta = st.session_state.step_meta
    valid = {step.uid for step in steps}

    for uid in list(meta):
        if uid not in valid:
            meta.pop(uid, None)
            for prefix in ("desc", "notes", "inc"):
                st.session_state.pop(f"{prefix}_{uid}", None)

    for step in steps:
        if step.uid not in meta:
            meta[step.uid] = {
                "description": step.description,
                "notes": "",
                "include": True,
                "deleted": False,
            }
        if not meta[step.uid].get("deleted"):
            _seed_widget_state(step.uid, meta[step.uid])

    st.session_state.rendered_count = len(steps)
    return steps


def _collect_export_steps(steps: list) -> list[ManualStep]:
    result: list[ManualStep] = []
    for step in steps:
        meta = st.session_state.step_meta.get(step.uid)
        if not meta or meta.get("deleted") or not meta.get("include", True):
            continue
        description = st.session_state.get(f"desc_{step.uid}", meta["description"])
        notes = st.session_state.get(f"notes_{step.uid}", meta["notes"])
        meta["description"] = description
        meta["notes"] = notes
        result.append(
            ManualStep(
                image_path=step.image_path,
                description=description,
                notes=notes,
                x=step.x,
                y=step.y,
                button=step.button,
                captured_at=step.captured_at,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Configuração atual do documento
# ---------------------------------------------------------------------------
def _current_config() -> ManualConfig:
    return ManualConfig(
        title=(st.session_state.doc_title or "").strip()
        or "Manual de Procedimentos",
        company=(st.session_state.doc_company or "").strip(),
        subtitle=(st.session_state.doc_subtitle or "").strip(),
        author=(st.session_state.doc_author or "").strip(),
        logo=st.session_state.logo_bytes,
        accent_color=_accent(),
        include_metadata=bool(st.session_state.doc_include_meta),
        page_break_per_step=bool(st.session_state.doc_page_break),
        generated_at=datetime.now(),
    )


def _fingerprint(config: ManualConfig, steps: list[ManualStep]) -> str:
    digest = hashlib.sha256()
    values = [
        config.title,
        config.company,
        config.subtitle,
        config.author,
        config.accent_color,
        str(config.include_metadata),
        str(config.page_break_per_step),
    ]
    for value in values:
        digest.update(value.encode("utf-8", "ignore"))
        digest.update(b"\x00")
    if config.logo:
        digest.update(config.logo)
    for step in steps:
        for value in (
            step.image_path,
            step.description,
            step.notes,
            str(step.x),
            str(step.y),
            step.button,
            step.captured_at.isoformat() if step.captured_at else "",
        ):
            digest.update(value.encode("utf-8", "ignore"))
            digest.update(b"\x00")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def _logo_is_valid(data: bytes) -> tuple[bool, str]:
    if len(data) > MAX_LOGO_BYTES:
        return False, "O arquivo tem mais de 5 MB. Use uma imagem menor."
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image.verify()
        if width < 32 or height < 32:
            return False, "A imagem é muito pequena. Use pelo menos 32 × 32 px."
        return True, ""
    except Exception:
        return False, "O arquivo não é uma imagem PNG ou JPG válida."


def _apply_recorder_settings(rec: ClickRecorder) -> None:
    if rec.running:
        return
    try:
        rec.configure(
            capture_delay=float(st.session_state.capture_delay),
            max_width=_max_width_value(),
            only_left_click=bool(st.session_state.only_left),
            enable_hotkeys=bool(st.session_state.enable_hotkeys),
        )
    except RecorderError as exc:
        st.session_state.recorder_error = str(exc)


def _render_sidebar(rec: ClickRecorder) -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="brand">
                <div class="brand-mark">📘</div>
                <div>
                    <div class="brand-name">Manual Auto</div>
                    <div class="brand-sub">Gerador de procedimentos</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="side-label">Gravação</div>', unsafe_allow_html=True)

        backend_ok, backend_message = backend_status()
        if not backend_ok:
            st.error(backend_message, icon="⚠️")

        _apply_recorder_settings(rec)

        status_class, status_label = _status_values(rec)
        st.markdown(
            f'<span class="status-pill {status_class}">'
            f'<span class="status-dot"></span>{status_label}</span>',
            unsafe_allow_html=True,
        )
        state_text = "pausado" if rec.paused else ("ativo" if rec.running else "parado")
        st.caption(
            f"{rec.count} captura(s) · {_duration(rec.elapsed_seconds)} · "
            f"{state_text}"
        )

        col_start, col_stop = st.columns(2)
        with col_start:
            start_clicked = st.button(
                "Iniciar",
                type="primary",
                icon=":material/fiber_manual_record:",
                width="stretch",
                disabled=rec.running or not backend_ok,
                help="A captura começa após o atraso configurado.",
            )
        with col_stop:
            stop_clicked = st.button(
                "Parar",
                icon=":material/stop_circle:",
                width="stretch",
                disabled=not rec.running,
                help="O clique neste botão não é incluído no manual.",
            )

        if rec.running:
            pause_label = "Retomar (F8)" if rec.paused else "Pausar (F8)"
            if st.button(
                pause_label,
                icon=":material/pause_circle:",
                width="stretch",
            ):
                rec.toggle_pause()
                st.rerun()

        if st.session_state.get("recorder_error"):
            st.error(st.session_state.recorder_error, icon="⚠️")

        if start_clicked:
            _apply_recorder_settings(rec)
            delay = int(st.session_state.start_delay)
            if delay > 0:
                with st.spinner(
                    f"A captura começa em {delay} segundos. "
                    "Alterne para a janela que deseja documentar."
                ):
                    time.sleep(delay)
            try:
                rec.start()
            except RecorderError as exc:
                st.session_state.recorder_error = str(exc)
                st.rerun()
            else:
                st.session_state.recorder_error = None
                st.session_state.rendered_count = rec.count
                st.session_state.last_running = True
                st.toast("Gravação iniciada. Minimize esta janela.", icon="🔴")
                st.rerun()

        if stop_clicked:
            rec.stop(discard_recent_seconds=1.2, reason="button")
            st.session_state.rendered_count = rec.count
            st.session_state.last_running = False
            st.toast("Gravação encerrada.", icon="⏹️")
            st.rerun()

        with st.expander("Configurações da captura", expanded=False):
            st.number_input(
                "Atraso para iniciar (s)",
                min_value=0,
                max_value=15,
                step=1,
                key="start_delay",
                disabled=rec.running,
                help="Tempo para minimizar a janela antes da primeira captura.",
            )
            st.number_input(
                "Atraso da captura (s)",
                min_value=0.0,
                max_value=2.0,
                step=0.05,
                key="capture_delay",
                disabled=rec.running,
                help="Espere um pouco após o clique para o menu abrir antes do screenshot.",
            )
            st.selectbox(
                "Largura máxima da imagem",
                options=["1280", "1600", "1920", "2560", "Original"],
                key="max_width",
                disabled=rec.running,
                help="Imagens menores deixam o .docx mais leve.",
            )
            st.checkbox(
                "Apenas clique esquerdo",
                key="only_left",
                disabled=rec.running,
            )
            st.checkbox(
                "Atalhos globais F8/F9",
                key="enable_hotkeys",
                disabled=rec.running,
                help="F8 pausa/retoma e F9 encerra a gravação.",
            )
            if rec.running:
                st.caption("Pare a gravação para alterar estas opções.")

        with st.expander("Limpeza e privacidade", expanded=False):
            st.caption(
                "As imagens ficam somente neste computador, em "
                "`storage/captures/`. Nada é enviado para a nuvem."
            )
            if st.button(
                "Limpar capturas desta sessão",
                type="tertiary",
                icon=":material/delete_sweep:",
                disabled=not rec.count and not rec.running,
                width="stretch",
            ):
                st.session_state.confirm_clear = True

            if st.session_state.confirm_clear:
                st.warning(
                    "Isso apaga todas as capturas e textos desta sessão. "
                    "A ação não pode ser desfeita."
                )
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button(
                        "Confirmar",
                        type="primary",
                        key="clear_yes",
                        width="stretch",
                    ):
                        rec.clear()
                        st.session_state.step_meta = {}
                        st.session_state.doc_bytes = None
                        st.session_state.doc_fingerprint = None
                        st.session_state.doc_filename = None
                        st.session_state.doc_generated_at = None
                        st.session_state.rendered_count = 0
                        st.session_state.last_running = False
                        st.session_state.confirm_clear = False
                        st.session_state.recorder_error = None
                        st.rerun()
                with cancel_col:
                    if st.button(
                        "Cancelar",
                        key="clear_no",
                        width="stretch",
                    ):
                        st.session_state.confirm_clear = False
                        st.rerun()

        st.divider()
        st.markdown('<div class="side-label">Documento</div>', unsafe_allow_html=True)
        st.text_input(
            "Título do manual",
            key="doc_title",
            placeholder="Manual de Procedimentos",
            max_chars=120,
        )
        st.text_input(
            "Nome da empresa",
            key="doc_company",
            placeholder="Sua Empresa Ltda.",
            max_chars=80,
        )
        st.text_input(
            "Subtítulo",
            key="doc_subtitle",
            placeholder="Treinamento de implantação",
            max_chars=120,
        )
        st.text_input(
            "Elaborado por",
            key="doc_author",
            placeholder="Equipe de Suporte",
            max_chars=80,
        )
        st.color_picker("Cor de destaque", key="doc_accent")

        logo_file = st.file_uploader(
            "Logo da empresa",
            type=["png", "jpg", "jpeg"],
            key=f"logo_upload_{st.session_state.logo_nonce}",
            help="PNG/JPG até 5 MB.",
        )
        if logo_file is not None:
            data = logo_file.getvalue()
            if data != st.session_state.logo_bytes:
                valid, message = _logo_is_valid(data)
                if valid:
                    st.session_state.logo_bytes = data
                    st.session_state.logo_name = logo_file.name
                else:
                    st.error(message, icon="⚠️")

        if st.session_state.logo_bytes:
            st.image(st.session_state.logo_bytes, width=150)
            st.caption(st.session_state.logo_name or "Logo carregada")
            if st.button(
                "Remover logo",
                key="remove_logo",
                type="tertiary",
                icon=":material/delete:",
            ):
                st.session_state.logo_bytes = None
                st.session_state.logo_name = ""
                st.session_state.logo_nonce += 1
                st.rerun()

        with st.expander("Opções do documento", expanded=False):
            st.checkbox(
                "Incluir dados da captura",
                key="doc_include_meta",
                help="Mostra data, hora, botão e coordenadas abaixo de cada passo.",
            )
            st.checkbox(
                "Um passo por página",
                key="doc_page_break",
                help="Cada passo começa em uma nova página do Word.",
            )

        st.divider()
        st.caption(
            "Processamento 100% local. Pause a gravação (F8) antes de "
            "editar os passos."
        )


def _status_values(rec: ClickRecorder) -> tuple[str, str]:
    if rec.running and rec.paused:
        return "paused", "Gravação pausada"
    if rec.running:
        return "recording", "Gravando"
    if rec.count:
        return "idle", "Gravação encerrada"
    return "idle", "Aguardando gravação"


# ---------------------------------------------------------------------------
# Status ao vivo
# ---------------------------------------------------------------------------
def _render_live_status(rec: ClickRecorder) -> None:
    @st.fragment(run_every=1.0 if rec.running else None)
    def _status_fragment() -> None:
        running = rec.running
        paused = rec.paused
        count = rec.count
        elapsed = _duration(rec.elapsed_seconds)
        status_class, status_label = _status_values(rec)

        if running and paused:
            hint = f"{count} captura(s) · {elapsed} · edite o manual com tranquilidade."
            banner = (
                '<div class="rec-banner paused"><strong>Captura pausada.</strong> '
                "Ajuste os textos e pressione <span class=\"rec-keys\">F8</span> "
                "quando estiver pronto para continuar.</div>"
            )
        elif running:
            hint = f"{count} captura(s) · {elapsed} · monitor do clique"
            banner = (
                '<div class="rec-banner"><strong>Gravação em andamento.</strong> '
                "Minimize esta janela e execute o processo no sistema. "
                'Use <span class="rec-keys">F8</span> para pausar e '
                '<span class="rec-keys">F9</span> para encerrar.</div>'
            )
        else:
            hint = (
                f"{count} captura(s) prontas para revisão."
                if count
                else "Configure o documento e clique em Iniciar na barra lateral."
            )
            banner = ""

        st.markdown(
            f'<div class="live-row">'
            f'<span class="status-pill {status_class}">'
            f'<span class="status-dot"></span>{status_label}</span>'
            f'<span class="live-hint">{hint}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if banner:
            st.markdown(banner, unsafe_allow_html=True)

        if rec.last_error:
            st.error(rec.last_error, icon="⚠️")
        elif rec.last_warning:
            st.warning(rec.last_warning, icon="⚠️")

        needs_rerun = False
        if count != st.session_state.get("rendered_count", 0):
            st.session_state.rendered_count = count
            needs_rerun = True
        if running != st.session_state.get("last_running", False):
            st.session_state.last_running = running
            needs_rerun = True
        if needs_rerun:
            st.rerun(scope="app")

    _status_fragment()


# ---------------------------------------------------------------------------
# Painel de passos
# ---------------------------------------------------------------------------
def _render_step_card(step, meta: dict, badge: str, muted: bool) -> None:
    uid = step.uid
    with st.container(border=True):
        head_badge, head_meta, head_action = st.columns(
            [0.5, 0.35, 0.15], vertical_alignment="center"
        )
        with head_badge:
            css_class = "step-badge muted" if muted else "step-badge"
            st.markdown(
                f'<span class="{css_class}">{html.escape(badge)}</span>',
                unsafe_allow_html=True,
            )
        with head_meta:
            st.caption(f"{step.time_label} · {step.button_label}")
        with head_action:
            if st.button(
                "Remover",
                key=f"remove_{uid}",
                type="tertiary",
                width="stretch",
                help="Remover este passo do manual.",
            ):
                meta["deleted"] = True
                st.rerun()

        image_col, form_col = st.columns([1.12, 1.0], gap="large")

        with image_col:
            if Path(step.image_path).exists():
                st.image(step.image_path, width="stretch")
                st.caption(
                    f"Captura original · {step.image_width} × {step.image_height} px"
                    + (f" · monitor {step.monitor}" if step.monitor else "")
                )
            else:
                st.warning("Imagem não encontrada no disco.", icon="🖼️")

        with form_col:
            description = st.text_input(
                "Descrição do passo",
                key=f"desc_{uid}",
                placeholder="Ex.: Clique em Arquivo > Salvar",
                max_chars=300,
            )
            notes = st.text_area(
                "Observações e instruções adicionais",
                key=f"notes_{uid}",
                height=120,
                placeholder="Dicas, avisos, resultados esperados...",
                max_chars=2000,
            )
            include = st.checkbox(
                "Incluir no documento",
                key=f"inc_{uid}",
                help="Desmarque para manter o passo na tela sem exportá-lo.",
            )
            location = f"({step.x}, {step.y})"
            if step.monitor:
                location += f" · monitor {step.monitor}"
            st.caption(f"{step.button_label} · {location}")
            if not include:
                st.caption("Este passo **não** será incluído no arquivo .docx.")

        meta["description"] = description
        meta["notes"] = notes
        meta["include"] = include


def _render_steps(steps: list) -> None:
    meta = st.session_state.step_meta
    removed = [step for step in steps if meta[step.uid].get("deleted")]
    visible = [step for step in steps if not meta[step.uid].get("deleted")]

    included_count = sum(1 for step in visible if meta[step.uid].get("include", True))
    unchecked_count = len(visible) - included_count

    metric_cols = st.columns(4)
    metric_cols[0].metric("Capturas", len(steps))
    metric_cols[1].metric("No documento", included_count)
    metric_cols[2].metric("Fora do documento", unchecked_count)
    metric_cols[3].metric("Removidos", len(removed))

    st.markdown("### Passos capturados")
    st.caption(
        "Edite a descrição, complemente com observações e desmarque o que não "
        "deve entrar no manual. A numeração final é recalculada na exportação."
    )

    sequence = 0
    for step in visible:
        step_meta = meta[step.uid]
        if step_meta.get("include", True):
            sequence += 1
            badge = f"Passo {sequence:02d}"
            muted = False
        else:
            badge = "Fora do documento"
            muted = True
        _render_step_card(step, step_meta, badge, muted)

    if removed:
        with st.expander(f"Passos removidos ({len(removed)})", expanded=False):
            for step in removed:
                info_col, action_col = st.columns(
                    [0.8, 0.2], vertical_alignment="center"
                )
                with info_col:
                    description = meta[step.uid].get("description") or "Sem descrição"
                    st.markdown(f"**Captura {step.number:02d}** — {description}")
                    st.caption(
                        f"{step.time_label} · {step.button_label} · "
                        f"({step.x}, {step.y})"
                    )
                with action_col:
                    if st.button(
                        "Restaurar",
                        key=f"restore_{step.uid}",
                        width="stretch",
                    ):
                        meta[step.uid]["deleted"] = False
                        st.rerun()


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def _render_export(steps: list) -> None:
    export_steps = _collect_export_steps(steps)
    config = _current_config()
    fingerprint = _fingerprint(config, export_steps)

    st.divider()
    st.markdown("### Exportar manual")
    st.caption(
        "O documento Word inclui capa, cabeçalho com a logo, imagens "
        "centralizadas, descrições e observações."
    )

    summary_col, action_col = st.columns([0.62, 0.38], vertical_alignment="center")
    with summary_col:
        if export_steps:
            st.markdown(
                f"**{len(export_steps)} passo(s)** serão exportados"
                + (f" com a identidade de **{html.escape(config.company)}**." if config.company else ".")
            )
            st.caption(
                f"Título: {config.title} · Formato: A4 · Word (.docx)"
            )
        else:
            st.warning(
                "Inclua ao menos um passo no documento para habilitar a exportação.",
                icon="📄",
            )
    with action_col:
        generate_clicked = st.button(
            "Gerar documento Word",
            type="primary",
            icon=":material/description:",
            width="stretch",
            disabled=not export_steps,
        )

    if generate_clicked:
        with st.spinner("Montando o documento..."):
            try:
                data = build_manual(config, export_steps)
            except Exception as exc:
                st.error("Não foi possível gerar o documento.", icon="⚠️")
                with st.expander("Detalhes técnicos"):
                    st.exception(exc)
            else:
                st.session_state.doc_bytes = data
                st.session_state.doc_fingerprint = fingerprint
                st.session_state.doc_filename = default_filename(config)
                st.session_state.doc_generated_at = datetime.now()
                st.toast("Documento gerado com sucesso.", icon="✅")

    if st.session_state.get("doc_bytes"):
        stale = st.session_state.get("doc_fingerprint") != fingerprint
        generated_at = st.session_state.get("doc_generated_at")
        info_col, download_col = st.columns([0.68, 0.32], vertical_alignment="center")
        with info_col:
            if stale:
                st.warning(
                    "O documento foi gerado antes das últimas alterações. "
                    "Gere novamente para atualizar a versão.",
                    icon="🔄",
                )
            else:
                size_kb = len(st.session_state.doc_bytes) / 1024
                when = generated_at.strftime("%H:%M") if generated_at else ""
                st.success(
                    f"Pronto · {st.session_state.doc_filename} · {size_kb:.0f} KB"
                    + (f" · gerado às {when}" if when else "")
                )
        with download_col:
            st.download_button(
                "Baixar .docx",
                data=st.session_state.doc_bytes,
                file_name=st.session_state.doc_filename
                or "manual_de_procedimentos.docx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                icon=":material/download:",
                width="stretch",
                type="primary" if not stale else "secondary",
            )


# ---------------------------------------------------------------------------
# Estado vazio
# ---------------------------------------------------------------------------
def _render_empty_state() -> None:
    st.markdown("### Nenhuma captura ainda")
    st.caption(
        "O fluxo é simples: configure a identidade, grave o processo e "
        "revise cada passo antes de gerar o Word."
    )
    columns = st.columns(3)
    guides = [
        (
            "1",
            "Configure o documento",
            "Na barra lateral, informe título, empresa, autor e envie a logo. "
            "Escolha a cor de destaque da identidade visual.",
        ),
        (
            "2",
            "Grave o processo",
            "Clique em Iniciar. A gravação começa após o atraso configurado; "
            "cada clique gera uma captura com o ponto marcado em vermelho.",
        ),
        (
            "3",
            "Revise e exporte",
            "Edite descrições, acrescente observações e desmarque o que não "
            "deve entrar. Depois gere e baixe o arquivo .docx.",
        ),
    ]
    for column, (number, title, text) in zip(columns, guides):
        with column:
            st.markdown(
                f'<div class="guide-card"><div class="guide-num">{number}</div>'
                f"<b>{html.escape(title)}</b><p>{html.escape(text)}</p></div>",
                unsafe_allow_html=True,
            )

    st.markdown("")
    with st.expander("Como a captura funciona", expanded=False):
        st.markdown(
            """
- A captura usa uma thread própria: a interface não trava durante os cliques.
- O screenshot mostra o **monitor onde o cursor estava**, com o ponto do clique circulado em vermelho.
- Use **F8** para pausar/retomar e **F9** para encerrar sem gerar uma captura extra.
- O clique no botão **Parar** da interface é descartado automaticamente.
- As imagens ficam em `storage/captures/` e nunca saem deste computador.
- **Dica:** minimize esta janela antes de gravar e pause (F8) antes de editar os passos.
            """
        )


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
def main() -> None:
    _init_state()
    rec = _recorder()
    _render_sidebar(rec)

    accent = _accent()
    st.markdown(
        f"<style>:root {{ --brand: {accent}; }}</style>",
        unsafe_allow_html=True,
    )

    steps = _sync_steps(rec)
    title = (st.session_state.doc_title or "").strip() or "Manual de Procedimentos"
    company = (st.session_state.doc_company or "").strip()

    chips = []
    if company:
        chips.append(
            f'<span class="hero-chip brand">{html.escape(company)}</span>'
        )
    chips.append(
        f'<span class="hero-chip">{len(steps)} captura(s)</span>'
    )
    if rec.running:
        chips.append('<span class="hero-chip">gravação ativa</span>')

    st.markdown(
        '<div class="hero">'
        '<div class="hero-kicker">Documentação automática</div>'
        f"<h1>{html.escape(title)}</h1>"
        "<p>Grave os cliques do processo, transforme cada captura em uma "
        "instrução clara e exporte um manual profissional em Word com a "
        "identidade visual da sua empresa.</p>"
        f'<div class="hero-chips">{"".join(chips)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    _render_live_status(rec)

    if not steps:
        _render_empty_state()
        st.divider()
        st.caption(
            "Dica: mantenha a barra lateral aberta para configurar o documento "
            "enquanto grava. As capturas aparecem aqui automaticamente."
        )
        return

    _render_steps(steps)
    _render_export(steps)

    st.divider()
    st.caption(
        "Manual Auto · 100% local · As capturas e o documento gerado ficam "
        "somente neste computador."
    )


if __name__ == "__main__":
    main()
