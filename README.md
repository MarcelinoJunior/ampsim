# AmpSim

Simulador de amplificador de guitarra e baixo + synth de pads, rodando localmente no Windows
com baixa latência (ASIO, WASAPI exclusivo ou WDM-KS).

- **Guitarra** e **Baixo**: cada um com sua entrada da placa de som e cadeia completa de efeitos.
- **Pads**: synth polifônico (16 vozes) tocado pelo **mouse** (teclado na tela), pelo
  **teclado do PC** ou por **teclado MIDI**, passando pela mesma cadeia de efeitos.
- As três trilhas tocam ao mesmo tempo e são mixadas na saída escolhida.

## Como rodar

Requisitos: Windows 10/11 e Python 3.11+ no PATH.

```bat
run.bat
```

Na primeira vez o `run.bat` cria o ambiente `.venv`, instala as dependências e compila o DSP
(leva ~20 s; depois fica em cache). Depois clique em **⚙ Áudio…**.

**Atalho na Área de Trabalho:** rode `criar_atalho.ps1` (botão direito → *Executar com o
PowerShell*) para criar o ícone **AmpSim**, que abre o app sem janela de console.
Para fechar, use o botão **⏻ Sair** no canto superior direito: ele salva a sessão, desliga o
áudio e encerra o programa. Erros inesperados ficam em `%APPDATA%\AmpSim\error.log`.

> Mantenha a pasta num caminho curto (ex.: `C:\Github\ampsim`). O PySide6 tem arquivos com
> nomes longos e a instalação falha em caminhos muito profundos.

Manualmente:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m ampsim
```

## Latência: qual driver usar

| API | Quando usar |
|---|---|
| **ASIO** | Melhor opção. Use o driver da sua interface; sem interface, **ASIO4ALL** ou **FlexASIO**. |
| WASAPI (exclusivo) | Boa alternativa sem ASIO. Marque "modo exclusivo". |
| WDM-KS | Latência baixa, mas alguns drivers são instáveis. |
| DirectSound / MME | Só como último recurso (latência alta). |

Dicas:

- O suporte a ASIO vem do PortAudio incluído no pacote `sounddevice` (ativado por
  `SD_ENABLE_ASIO=1`, que o app já define).
- No ASIO, o tamanho real do buffer costuma ser definido pelo driver: use o botão
  **Painel do driver ASIO…** (no ASIO4ALL, comece com 64–128 amostras).
- Com ASIO, entrada e saída precisam ser o mesmo driver (limitação do ASIO).
- A barra superior mostra a latência informada pelo driver, a carga de CPU do callback e o
  número de falhas (dropouts). Se aparecerem falhas, aumente o buffer.
- O app roda com prioridade alta e o DSP é compilado para código nativo (Numba), sem
  alocação de memória dentro do callback de áudio.

## Cadeia de efeitos (igual para as três trilhas)

```
Redutor de Ruído → Noise Gate → Compressor → Overdrive → Amplificador → Captura NAM
           → Plugin VST3 → Gabinete → EQ 5 bandas
           → Chorus (estéreo) → Delay (ping-pong opcional) → Reverb → Volume/Pan
```

- **Redutor de Ruído**: anti-hum (notches em 50/60 Hz e harmônicos), anti-chiado (filtro
  que fecha os agudos quando você não está tocando), corte de graves e de agudos.
- **Calibrar ruído** (cabeçalho das trilhas Guitarra/Baixo): abafe as cordas e clique; o app
  mede o chiado da entrada por 2 s e ajusta os limiares do Gate e do Redutor de Ruído.
  Entradas de microfone de placas USB simples costumam ter bastante chiado: com distorção ele
  vira um "zunido" agudo se o gate ficar abaixo do ruído.
- **Amplificador**: 7 modelos inspirados em clássicos, cada um com fachada própria (tecido,
  logo e painel desenhados no estilo do original, sem marcas):

  | Modelo | Estilo de | Uso |
  |---|---|---|
  | Blackface Twin | Fender Twin Reverb | limpo cristalino |
  | Brit Plexi | Marshall Super Lead 1959 | crunch clássico |
  | Brit 800 | Marshall JCM800 2203 | rock / solo |
  | AC Top Boost | Vox AC30 Top Boost | brilho "chime" |
  | Recto Modern | Mesa/Boogie Dual Rectifier | hi-gain moderno |
  | SVT Classic | Ampeg SVT | baixo valvulado |
  | Bass Drive | pré-amps de baixo modernos | baixo com drive |

  Gain, Graves, Médios, Agudos, Presença, Master e **Blend DI** (mistura sinal limpo — útil
  no baixo para manter o grave). A distorção roda com oversampling 4x.
- **Captura NAM (amp real)**: roda capturas do [Neural Amp Modeler](https://github.com/sdatkinson/NeuralAmpModelerPlugin)
  (`.nam`, arquitetura WaveNet) **direto no AmpSim, em código nativo** — sem precisar do
  plugin. Cada captura é o "DNA" de um amplificador real medido por alguém; o volume é
  normalizado automaticamente. Use com o Amplificador desligado e o Gabinete ligado (as
  capturas incluídas são só do amp, sem falante). Custa ~9% de CPU com buffer de 64.
- **Plugin VST3**: carrega qualquer plugin de efeito VST3 (amp sims, pedais, reverbs) da
  pasta `C:\Program Files\Common Files\VST3`, com **Abrir editor** para a interface do
  plugin e **Mix** seco/molhado. O estado do plugin é salvo nos presets.
- **Gabinete**: 6 modelos (3 de guitarra, 3 de baixo) ou **IR em .wav** (convolução direta,
  latência zero, até 2048 amostras). Aceita WAV PCM 16/24/32 bits e float.
- Cada efeito tem LED liga/desliga. Os presets de fábrica são marcados com ★; use
  **Salvar…** para criar os seus.

## Capturas NAM e plugins (extras do GitHub)

```bat
.venv\Scripts\python tools\baixar_extras.py
```

Baixa para `third_party/` (fora do git):

- **9 capturas gratuitas** da coleção [pelennor2170/NAM_models](https://github.com/pelennor2170/NAM_models)
  (GPL-3.0): Fender Twin Reverb, Vox AC15 Top Boost, Marshall JCM2000 Crunch, Marshall
  JCM900 Lead, Mesa Boogie Mark IV, EVH 5150, Soldano SLO, Orange Rockerverb e o pré de
  baixo Tech21 dUg DP3X. Os presets "NAM · …" de guitarra e baixo usam essas capturas.
- **Instalador do plugin Neural Amp Modeler** (MIT). Ele é opcional — o AmpSim já roda as
  capturas sozinho — e serve para quem quiser usar o plugin oficial no slot VST3. O
  instalador não é assinado digitalmente; execute-o só se confiar na fonte (release oficial).

Com o plugin instalado, escolha **NeuralAmpModeler** no painel *Plugin VST3*, clique em
**Abrir editor** e carregue um `.nam` (ex.: os de `third_party\nam_models`) e, se quiser, uma
IR de gabinete. Feche a janela do plugin para voltar ao AmpSim — o som não para enquanto ela
está aberta, e o que você escolheu fica salvo no preset.

Para usar outras capturas (ex.: do site ToneHunt), clique em **Adicionar captura…** no
painel NAM: o arquivo é copiado para `%APPDATA%\AmpSim\nam`.

## Controles

**Knobs**: arraste para cima/baixo (Shift = ajuste fino), roda do mouse, duplo-clique volta ao padrão.

**Teclado do PC → pads** (funciona em ABNT2 e US, usa a posição física das teclas):

```
 W E   T Y U   O P          ← teclas pretas
A S D F G H J K L Ç         ← teclas brancas (A = Dó)
Z / X = oitava −/+     C / V = velocidade −/+
```

**MIDI**: escolha a entrada na barra inferior. Suporta note on/off com velocidade, sustain
(CC64), pitch bend, mod wheel (CC1 → LFO do filtro) e all notes off. **Pânico** solta todas as notas.

## Onde ficam os dados

`%APPDATA%\AmpSim\state.json` (última sessão, dispositivos, knobs) e
`%APPDATA%\AmpSim\presets\<guitar|bass|pads>\*.json`.

## Estrutura

```
ampsim/
  __main__.py        entrada (prioridade, splash, compilação do DSP)
  audio/devices.py   APIs/dispositivos (PortAudio), painel ASIO
  audio/engine.py    stream duplex e callback em tempo real
  dsp/kernels.py     DSP em Numba: efeitos, amp, gabinete, synth
  dsp/nam.py         inferência nativa de capturas Neural Amp Modeler (WaveNet + BLAS)
  audio/vst.py       slot de plugin VST3 (pedalboard)
  ui/amp_skins.py    fachadas dos amplificadores
  dsp/track.py       knobs → coeficientes de cada trilha
  dsp/synth.py       parâmetros e sons do synth de pads
  dsp/params.py      faixas/padrões dos parâmetros, modelos de amp e gabinete
  midi/winmm.py      entrada MIDI nativa do Windows (ctypes, sem dependências)
  ui/                interface PySide6 (knobs, piano, painéis, diálogo de áudio)
tests/test_dsp.py    testes offline (estabilidade, IR vs. numpy, orçamento de CPU)
```

Testes: `.venv\Scripts\pip install pytest` e `.venv\Scripts\python -m pytest -s`.
O teste de desempenho imprime quanto da janela de 64 amostras o DSP completo consome.

## Licenças de terceiros

`pedalboard` (Spotify) é GPL-3.0; as capturas NAM incluídas pelo script são GPL-3.0; o
plugin Neural Amp Modeler é MIT. Os nomes de equipamentos citados identificam o estilo ou o
equipamento capturado e pertencem aos seus donos; não há afiliação.

## Próximos passos sugeridos

- MIDI learn (mapear knobs para controladores MIDI) e troca de preset por Program Change.
- Pads com samples (.wav) além do synth.
- Afinador, looper e gravação da saída.
