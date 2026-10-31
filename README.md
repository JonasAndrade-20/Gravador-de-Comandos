# 📘 Manual Auto — Gerador de Manuais e Procedimentos

Aplicação local em **Python + Streamlit** que grava os cliques de um processo,
captura a tela com o ponto do clique destacado, permite revisar cada etapa e
exporta um manual profissional em **Word (.docx)** com a identidade visual da
sua empresa.

Todo o processamento acontece na sua máquina. As imagens e os documentos não
são enviados para nenhum serviço externo.

---

## ✨ Recursos

- **Gravação em segundo plano:** o `pynput` escuta os cliques e uma thread
  separada faz as capturas, sem congelar a interface do Streamlit.
- **Captura no monitor certo:** o screenshot é tirado no monitor onde o clique
  aconteceu, com o ponto exato circulado em vermelho (Pillow).
- **Controle por atalhos:** `F8` pausa/retoma e `F9` encerra a gravação.
- **Edição completa:** descrição, observações/instruções adicionais, inclusão
  ou remoção de passos, com restauração de passos removidos.
- **Documento profissional:** capa, logo no cabeçalho, rodapé com numeração,
  títulos com estilos nomeados, imagens centralizadas, legendas e caixas de
  observações.
- **Download direto:** o `.docx` é gerado em memória e baixado pelo navegador.
- **100% local:** os arquivos ficam em `storage/captures/`.

---

## 🗂 Estrutura do projeto

```
Gravador de Comandos/
├── app.py                  # Interface Streamlit
├── recorder.py             # Listener de cliques + screenshots + marcador
├── exporter.py             # Geração do documento .docx
├── requirements.txt        # Dependências
├── run.bat                 # Atalho de execução no Windows
├── README.md
├── .streamlit/
│   └── config.toml         # Tema visual do Streamlit
└── storage/
    └── captures/           # Criado automaticamente; capturas locais
```

---

## ✅ Requisitos

- **Python 3.10 ou superior** (testado com Python 3.14 no Windows 11).
- Windows 10/11, macOS ou Linux com **X11**.
- Acesso a uma sessão gráfica (a gravação não funciona em servidores sem
  interface, e o Wayland não é suportado pelos hooks globais do `pynput`).

---

## 🚀 Instalação

### Windows (PowerShell)

```powershell
cd "C:\Documentos Importantes\Programas Python\Gravador de Comandos"

# Ambiente virtual (recomendado)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Se o PowerShell bloquear a ativação:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

python -m pip install --upgrade pip
pip install -r requirements.txt
```

> Não quer usar ambiente virtual? Rode `pip install -r requirements.txt` com o
> Python global e siga para a execução.

### macOS / Linux

```bash
cd "caminho/para/Gravador de Comandos"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## ▶️ Executar

```bash
streamlit run app.py
```

O Streamlit abre automaticamente `http://localhost:8501`. Se a porta estiver
ocupada:

```bash
streamlit run app.py --server.port 8502
```

No Windows também é possível dar duplo clique em **`run.bat`**.

---

## 🧭 Como usar

1. **Configure o documento** na barra lateral:
   - título, empresa, subtítulo e responsável;
   - cor de destaque;
   - logo (PNG/JPG, até 5 MB).
2. **Ajuste a gravação** em *Configurações da captura*:
   - atraso para iniciar (dá tempo de minimizar a janela);
   - atraso do screenshot (útil para menus que abrem após o clique);
   - largura máxima da imagem (deixe em 1920 para um bom equilíbrio);
   - capturar apenas clique esquerdo.
3. Clique em **Iniciar**. Durante o atraso, alterne para o sistema que será
   documentado.
4. Execute o processo normalmente. Cada clique gera uma etapa com a tela
   capturada e o ponto do clique marcado em vermelho.
5. Use **F8** para pausar/retomar e **F9** para encerrar. Você também pode usar
   os botões da barra lateral.
6. Na área principal:
   - edite a **descrição** de cada passo;
   - acrescente **observações** e instruções extras;
   - desmarque **Incluir no documento** para manter o passo na tela sem
     exportá-lo;
   - use **Remover** para tirar o passo da lista (ele pode ser restaurado no
     final da página).
7. Clique em **Gerar documento Word** e depois em **Baixar .docx**.

> **Dica importante:** minimize a janela do navegador antes de gravar. Se
> precisar editar os passos enquanto grava, pause com **F8** para não capturar
> os cliques na própria interface.

### Sobre a numeração

A interface mostra a ordem dos passos incluídos. Ao excluir ou desmarcar um
passo, a numeração do documento é recalculada na exportação, sem buracos.

---

## 🔐 Permissões do sistema operacional

### Windows

Normalmente não é necessário conceder permissão especial. Se a captura sair
preta ou vazia:

- execute o terminal/Python fora de sessões de Área de Trabalho Remota
  restritas;
- libere o Python/Streamlit no antivírus (o `pynput` instala um hook global de
  mouse e teclado, o que alguns antivírus monitoram);
- evite capturar telas de aplicativos protegidos (janelas de UAC, conteúdo
  DRM, alguns apps bancários), que bloqueiam screenshots por segurança;
- mantenha a escala do Windows em 100%, 125% ou 150% — o aplicativo ativa o
  *DPI awareness* para alinhar o clique à imagem.

### macOS

O macOS exige autorização explícita:

1. **Ajustes do Sistema → Privacidade e Segurança → Gravação de Tela**:
   permita o **Terminal**, iTerm, VS Code ou o Python usado para executar.
2. **Privacidade e Segurança → Acessibilidade** (e, em versões recentes,
   **Monitoramento de Entrada**): permita o mesmo aplicativo, necessário para
   o `pynput`.
3. **Feche e reabra o terminal** após conceder as permissões.
4. Em telas Retina, a escala é detectada automaticamente. Se o marcador
   aparecer deslocado, defina `MANUAL_COORD_SCALE=2` antes de iniciar o
   Streamlit.

### Linux

- É necessário usar **X11**. Verifique com `echo $XDG_SESSION_TYPE`; se
  retornar `wayland`, faça login em uma sessão X11 (ou Xorg).
- Dependências usuais em Debian/Ubuntu:
  ```bash
  sudo apt install python3-dev libx11-6 libxext6 libxrender1
  ```
- O `pynput` usa `python-xlib` (instalado como dependência) e não precisa de
  root para escutar cliques na sessão gráfica.
- Atalhos globais podem não funcionar em alguns ambientes; use os botões da
  interface.

---

## 🧪 Solução de problemas

| Sintoma | Causa provável / solução |
|---|---|
| `ModuleNotFoundError: pynput` | Ative o ambiente virtual e rode `pip install -r requirements.txt`. |
| Botão **Iniciar** desabilitado | O backend de captura não carregou (Linux sem X11, dependência ausente). Veja a mensagem na barra lateral. |
| Capturas totalmente pretas | macOS: permissão de Gravação de Tela; Windows: RDP, DRM ou antivírus. |
| F8/F9 não funcionam | Outro programa capturou a tecla ou faltam permissões de Acessibilidade. Use os botões da barra lateral. |
| Marcador deslocado no Mac | `MANUAL_COORD_SCALE=2` (ou o fator da sua tela) antes de iniciar o app. |
| O clique no botão *Parar* virou um passo | O aplicativo descarta automaticamente a última captura feita há menos de 1,2 s. Se ainda aparecer, remova o passo manualmente. |
| Documento muito pesado | Reduza a largura máxima para 1280 ou 1600 px nas configurações da captura. |
| Números de página não aparecem no Word | São campos do Word; pressione `Ctrl+A` e depois `F9` para atualizar. |
| Porta 8501 em uso | `streamlit run app.py --server.port 8502`. |
| A interface trava ao gravar | A captura roda em outra thread; verifique se o antivírus não está bloqueando o `mss`/`pynput`. |

---

## 🧠 Como funciona (arquitetura)

- **`recorder.py`**
  - `pynput.mouse.Listener` roda em uma thread própria e apenas enfileira o
    clique (rápido, sem bloquear).
  - Uma thread trabalhadora consome a fila, tira o screenshot com `mss` no
    monitor do clique, redimensiona opcionalmente, desenha o marcador com
    `Pillow` e grava o PNG de forma atômica.
  - `Step` é imutável e protegido por lock; a interface pode ler os passos a
    qualquer momento.
  - `F8`/`F9` usam `pynput.keyboard.GlobalHotKeys`, com fallback silencioso se
    o sistema não permitir.
- **`exporter.py`**
  - `python-docx` monta capa, seção de conteúdo, cabeçalho/rodapé e os blocos
    de cada passo.
  - Estilos nomeados (`Manual Step Title`, `Manual Caption`, etc.) usam Calibri
    e a cor de destaque escolhida.
  - O logo é normalizado para PNG via Pillow e aplicado na capa e no cabeçalho.
  - A numeração de páginas usa campos nativos do Word (`PAGE` e
    `SECTIONPAGES`).
- **`app.py`**
  - O gravador fica no `st.session_state`, sobrevivendo aos reruns.
  - Um `st.fragment` com `run_every=1s` atualiza o status ao vivo e dispara um
    rerun quando uma nova captura chega.
  - A exportação gera os bytes em memória e usa `st.download_button`.

---

## 🎨 Personalização

- **Cores e fontes do Word:** constantes no topo de `exporter.py`
  (`DEFAULT_ACCENT`, `FONT`, `TEXT_COLOR`). A cor de destaque também pode ser
  alterada pela interface.
- **Tamanho das imagens no documento:** ajuste os limites em
  `_add_image_block` (largura máxima de 16,2 cm e altura de 16,5 cm).
- **Tema do Streamlit:** edite `.streamlit/config.toml`.
- **Atalhos:** altere o dicionário de `GlobalHotKeys` em `recorder.py`.

---

## 🧹 Privacidade e limpeza

- As capturas ficam em `storage/captures/<sessão>/`.
- Use **Limpar capturas desta sessão** na barra lateral para apagar as imagens
  e os textos da sessão atual.
- Para remover capturas antigas, feche o aplicativo e apague manualmente as
  subpastas de `storage/captures/`.
- Nenhum dado é enviado para servidores externos. O Streamlit roda apenas em
  `localhost` por padrão.

---

## ⚠️ Limitações conhecidas

- Captura o **monitor onde o clique ocorreu**; janelas que cruzam dois
  monitores aparecem apenas no monitor do clique.
- O cursor do mouse não é desenhado na imagem; o local é indicado pelo círculo
  vermelho.
- Aplicativos com proteção contra screenshots podem renderizar uma área preta.
- O Wayland não permite hooks globais de mouse/teclado pelo `pynput`.
- A gravação depende de uma sessão gráfica ativa no mesmo computador do
  navegador.

---

## 🛠 Verificação rápida

```bash
python -m py_compile app.py recorder.py exporter.py
streamlit run app.py
```

Se o app abrir, a barra lateral mostrar **“Aguardando gravação”** e o botão
**Iniciar** estiver habilitado, o ambiente está pronto.

---

Feito para transformar aquele processo que só existe na cabeça de alguém em
um manual claro, bonito e reutilizável. 📘
