# Créditos e licenças de terceiros

O AmpSim é distribuído sob a **GNU General Public License v3.0** (arquivo [LICENSE](LICENSE)).
Abaixo está tudo o que vem de outras pessoas, com a licença de cada parte. Nenhum desses
arquivos fica guardado neste repositório. As bibliotecas são instaladas pelo `pip`, e os timbres
e motores são baixados das fontes oficiais pelo `tools/baixar_extras.py`.

## Código e algoritmos

| Origem | Uso no AmpSim | Licença |
|---|---|---|
| [NeuralAmpModelerCore](https://github.com/sdatkinson/NeuralAmpModelerCore), Steven Atkinson | A inferência WaveNet das capturas NAM (`ampsim/dsp/nam.py`) foi reescrita em Python/Numba seguindo a arquitetura desse projeto. As constantes da aproximação `fast_tanh` vêm dele. | MIT. Copyright (c) 2023 Steven Atkinson |
| Freeverb, Jezar at Dreampoint | Estrutura do reverb (filtros comb + allpass) | Domínio público |
| Robert Bristow-Johnson, *Audio EQ Cookbook* | Fórmulas dos filtros biquad | Uso livre (fórmulas publicadas) |
| Vadim Zavalishin, *The Art of VA Filter Design* | Filtro SVF TPT do synth | Técnica publicada |
| PolyBLEP (Välimäki et al.) | Osciladores sem aliasing do synth | Técnica publicada |

### Aviso MIT (NeuralAmpModelerCore)

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software
> and associated documentation files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions: The above copyright notice
> and this permission notice shall be included in all copies or substantial portions of the
> Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

## Bibliotecas (instaladas pelo pip)

| Biblioteca | Licença |
|---|---|
| [pedalboard](https://github.com/spotify/pedalboard) (Spotify, inclui JUCE) | GPL-3.0. É o motivo de o AmpSim ser GPL-3.0. |
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | LGPL-3.0 |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) + [PortAudio](http://www.portaudio.com/) | MIT |
| [NumPy](https://numpy.org/), [SciPy](https://scipy.org/), [Numba](https://numba.pydata.org/) | BSD |

## Baixados na instalação

| Item | Licença |
|---|---|
| [FluidSynth](https://github.com/FluidSynth/fluidsynth): motor de SoundFont, carregado como DLL separada | LGPL-2.1 |
| [GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS), S. Christian Collins: banco de timbres | Licença própria e livre, inclusive para uso comercial (cópia em `third_party/soundfonts/`) |
| [Capturas NAM](https://github.com/pelennor2170/NAM_models): coleção da comunidade | GPL-3.0 |
| [Neural Amp Modeler (plugin)](https://github.com/sdatkinson/NeuralAmpModelerPlugin) | MIT |
| [ASIO4ALL](https://asio4all.org), Michael Tippach | Freeware |
| [FlexASIO](https://github.com/dechamps/FlexASIO), Etienne Dechamps | MIT |

## Timbres: são exemplos, não cópias

Os sons do AmpSim são **exemplos**. Uns são criados pelo próprio programa (synth, bateria
sintetizada, reverbs). Outros vêm de bancos gratuitos (GeneralUser GS). **Nenhum deles é cópia
ou amostra do som dos equipamentos originais.** Os nomes dos amplificadores e teclados indicam
só o *estilo* que inspirou o desenho da tela.

## Marcas registradas

Marshall, Fender, Mesa/Boogie, Vox, Ampeg, Yamaha, Roland, M-VAVE e as demais marcas
citadas pertencem aos seus titulares. Os desenhos na tela são homenagens. O AmpSim não é
afiliado a esses fabricantes nem endossado por eles. ASIO é marca da Steinberg Media
Technologies GmbH.
