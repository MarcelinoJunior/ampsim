# Créditos e licenças de terceiros

O AmpSim é distribuído sob a **GNU General Public License v3.0** (arquivo [LICENSE](LICENSE)).
Abaixo está tudo o que vem de outras pessoas, com a licença de cada parte. Nenhum desses
arquivos fica guardado neste repositório, exceto as fotos dos timbres (ver abaixo). As bibliotecas são instaladas pelo `pip`, e os timbres
e motores são baixados pelo `tools/baixar_extras.py` de uma cópia sem modificações publicada
no release [extras-1](https://github.com/MarcelinoJunior/ampsim/releases/tag/extras-1). Essa cópia
traz as licenças (pasta `licencas/`) e o código-fonte do FluidSynth, exigido pela LGPL. Se ela
falhar, o script baixa das fontes oficiais listadas abaixo.

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

## Fotos dos timbres (guardadas no repositório)

As miniaturas do timbre (quadrado ao lado do nome) são fotos do [Wikimedia Commons](https://commons.wikimedia.org/).
Elas ficam no repositório, em `assets/timbres/`, recortadas em quadrado e reduzidas para 192×192 px.
Cada uma continua sob a licença original. As versões recortadas das fotos CC BY-SA são distribuídas
sob a mesma licença CC BY-SA.

| Arquivo | Usada em | Foto original | Autor | Licença |
|---|---|---|---|---|
| `assets/timbres/piano.jpg` | Pianos | [Fritz Dobbert Grand Piano from the 1980's.jpg](https://commons.wikimedia.org/wiki/File:Fritz_Dobbert_Grand_Piano_from_the_1980%27s.jpg) | Vrsooo | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/epiano.jpg` | Pianos elétricos | [1977 Rhodes Mark I Suitcase Piano 73-key (serial no. K610578) (2005-01-29 09.27.49 by Daniel Spils).jpg](https://commons.wikimedia.org/wiki/File:1977_Rhodes_Mark_I_Suitcase_Piano_73-key_(serial_no._K610578)_(2005-01-29_09.27.49_by_Daniel_Spils).jpg) | Daniel Spils from Seattle, USA | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/organ.jpg` | Órgãos | [Hammond-museum-1.png](https://commons.wikimedia.org/wiki/File:Hammond-museum-1.png) | Фіксер | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/tubos.jpg` | Órgão de tubos | [Cathedral of Albi - Nave and Organ - 7029.jpg](https://commons.wikimedia.org/wiki/File:Cathedral_of_Albi_-_Nave_and_Organ_-_7029.jpg) | PierreSelim | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) |
| `assets/timbres/pad.jpg` | Pads | [Aurora Borealis NO.JPG](https://commons.wikimedia.org/wiki/File:Aurora_Borealis_NO.JPG) | Rafal Konieczny | [CC BY 2.5](https://creativecommons.org/licenses/by/2.5) |
| `assets/timbres/cordas.jpg` | Cordas | [Old Wooden Cello - Flickr - dejankrsmanovic.jpg](https://commons.wikimedia.org/wiki/File:Old_Wooden_Cello_-_Flickr_-_dejankrsmanovic.jpg) | Dejan Krsmanovic | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/coral.jpg` | Coral | [Howard Gospel Choir 2 (4369636665).jpg](https://commons.wikimedia.org/wiki/File:Howard_Gospel_Choir_2_(4369636665).jpg) | US Embassy Sweden | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/baixo.jpg` | Baixos | [0-ESP Ltd F 255 electric bass guitar body 08.jpg](https://commons.wikimedia.org/wiki/File:0-ESP_Ltd_F_255_electric_bass_guitar_body_08.jpg) | Elmschrat | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/violao.jpg` | Violões | [00 Walden Acoustic Guitar D310e body.jpg](https://commons.wikimedia.org/wiki/File:00_Walden_Acoustic_Guitar_D310e_body.jpg) | Elmschrat | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/guitarra.jpg` | Guitarras | [1958 Fender Stratocaster.jpg](https://commons.wikimedia.org/wiki/File:1958_Fender_Stratocaster.jpg) | User:Lightburst | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/sinos.jpg` | Sinos e outros | [RCAStudioB Vibraphone 1.jpg](https://commons.wikimedia.org/wiki/File:RCAStudioB_Vibraphone_1.jpg) | Cliff from I now live in Arlington, VA (Outside Washington DC), USA | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/synth.jpg` | Synth AmpSim | [Clavia Nord Lead 3 - filter 1 - Advanced Subtractive ....jpg](https://commons.wikimedia.org/wiki/File:Clavia_Nord_Lead_3_-_filter_1_-_Advanced_Subtractive_....jpg) | Kazuhisa OTSUBO | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |

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
