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
- **Amplificador**: escolhido num seletor único no topo (modelos AmpSim, capturas NAM,
  plugins VST3 ou sem amp). Cada amp aparece com a fachada no estilo do original: tecido,
  painel, knobs (top hat, chicken head, saia numerada...), jacks, luz piloto e chaves:

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

## Pad/Piano (controlador MIDI)

A aba **Pad/Piano** mostra o instrumento na tela — escolha entre **M-VAVE SMK-25** (25 teclas,
8 pads, 8 knobs, 8 botões), **Yamaha PSR-E473** (61 teclas) e **Roland VR-730** (73 teclas).
Tudo nele é clicável, acende quando você toca no aparelho, e o **botão direito** em um pad,
knob, botão ou tecla abre a escolha do som ou da função.

- **Timbres prontos para louvor**: Piano + Pad, Piano + Cordas, Rhodes + Pad, Pad + Cordas,
  Baixo | Piano (divisão em C3: baixo na mão esquerda), Baixo Synth | Rhodes, Órgão + Pad,
  Violão, Guitarra Limpa e o Pad do synth do AmpSim.
- **Teclas / Camada 2**: escolha qualquer um dos ~45 timbres (pianos, Rhodes, órgãos, pads,
  cordas, baixos, violões, guitarras, sinos) e uma segunda camada **sobreposta** ou na
  **mão esquerda** (divisão do teclado, com nota ajustável).
- **Pads**: tocam bateria — bumbo, caixa, aro, palmas, chimbal, pratos, toms, shaker,
  pandeirola… — escolhida pad a pad, com 7 kits (Acústico, Power, Eletrônico, 808/909,
  Vassourinha…). A bateria sai sempre limpa, em estéreo.
- **Knobs e botões**: cada um recebe uma função (volume das teclas, da camada 2 e da bateria,
  reverb, chorus, brilho, release, master; timbre/kit anterior e próximo, liga/desliga
  camada 2, pânico).
- **Mapear meu controlador…**: assistente que pede "toque o PAD 1", "gire o KNOB 1",
  "aperte o botão PLAY"… e aprende o que o seu controlador envia (com **Pular** e **Parar**).
  Sem mapear, os pads esperam as notas 36–43 no canal 10.
- **Teclas passam pelo amplificador** (no topo da aba): desligado, o timbre sai limpo, com
  reverb/chorus próprios; ligado, as teclas passam pelo amplificador, gabinete e pedais da
  aba (útil para o timbre de guitarra).
- As visões **Synth AmpSim** e **Amplificador e efeitos** ficam em botões no topo da aba.

Conecte o controlador pelo **USB** e escolha-o em **MIDI:** na barra de baixo (o MIDI por
Bluetooth não aparece nessa lista do Windows).

Os timbres vêm do banco **GeneralUser GS** tocado pelo **FluidSynth**, ambos baixados por
`toolsaixar_extras.py`.

## Capturas NAM e plugins (extras do GitHub)

```bat
.venv\Scripts\python tools\baixar_extras.py
```

Baixa para `third_party/` (fora do git):

- **FluidSynth** (motor dos timbres das teclas e pads, LGPL-2.1; hash SHA-256 conferido) e o
  banco **GeneralUser GS** (~260 timbres e 13 kits de bateria, licença livre).

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
plugin Neural Amp Modeler é MIT; FluidSynth é LGPL-2.1 (carregado como DLL); GeneralUser GS
usa a licença própria do autor (uso livre, inclusive comercial).

## Marcas registradas

Fender, Marshall, Mesa/Boogie, Vox, Ampeg, Orange, EVH, Soldano, Tech 21, M-VAVE e demais nomes de
equipamentos citados são marcas registradas de seus respectivos titulares. O AmpSim não é
afiliado, patrocinado nem endossado por nenhum deles. Os nomes aparecem apenas para
identificar o estilo de timbre que cada modelo busca ou o equipamento real capturado (NAM).
As fachadas são desenhos próprios, com os nomes escritos em fontes comuns, e não reproduzem
logotipos oficiais. Cada fachada exibe esse aviso na própria tela.

## Próximos passos sugeridos

- MIDI learn (mapear knobs para controladores MIDI) e troca de preset por Program Change.
- Pads com samples (.wav) além do synth.
- Afinador, looper e gravação da saída.
