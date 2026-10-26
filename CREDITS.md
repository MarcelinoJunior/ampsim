# Créditos e licenças de terceiros

O AmpSim é distribuído sob a **GNU General Public License v3.0** (arquivo [LICENSE](LICENSE)).
Abaixo está tudo o que vem de outras pessoas, com a licença de cada parte. Nenhum desses
arquivos fica guardado neste repositório, exceto as imagens dos timbres (ver abaixo). As bibliotecas são instaladas pelo `pip`, e os timbres
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

## Imagens dos timbres (guardadas no repositório)

Cada timbre tem uma miniatura própria (o quadrado ao lado do nome). As imagens ficam no repositório,
em `assets/timbres/`, recortadas em quadrado e reduzidas para 192×192 px.

- **Fotos** (`assets/timbres/*.jpg`, menos as `synth-*`): vêm do [Wikimedia Commons](https://commons.wikimedia.org/).
  Cada uma continua sob a licença original, listada abaixo. As versões recortadas das fotos CC BY-SA
  são distribuídas sob a mesma licença CC BY-SA.
- **Artes dos timbres do synth AmpSim** (`assets/timbres/synth-*.jpg`): desenhadas pelo próprio AmpSim
  (`tools/gerar_artes_synth.py`), sob a mesma licença do projeto (GPL-3.0).

| Arquivo | Timbre | Foto original | Autor | Licença |
|---|---|---|---|---|
| `assets/timbres/baixo-101.jpg` | Baixo Synth 101 | [Roland SH-101 logo.jpg](https://commons.wikimedia.org/wiki/File:Roland_SH-101_logo.jpg) | Mickey Destro | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/baixo-acustico.jpg` | Baixo Acústico | [AGK bass1 full.jpg](https://commons.wikimedia.org/wiki/File:AGK_bass1_full.jpg) | User:AndrewKepert | [CC BY-SA 3.0](http://creativecommons.org/licenses/by-sa/3.0/) |
| `assets/timbres/baixo-finger.jpg` | Baixo Finger | [0-ESP Ltd F 255 electric bass guitar body 08.jpg](https://commons.wikimedia.org/wiki/File:0-ESP_Ltd_F_255_electric_bass_guitar_body_08.jpg) | Elmschrat | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/baixo-fm.jpg` | Baixo FM | [DX7IIDmainboard.jpg](https://commons.wikimedia.org/wiki/File:DX7IIDmainboard.jpg) | Metroplex | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/baixo-fretless.jpg` | Baixo Fretless | [AX Stagg Fretless Bass Fingerboard.jpg](https://commons.wikimedia.org/wiki/File:AX_Stagg_Fretless_Bass_Fingerboard.jpg) | Serguei Trouchelle 11:48, 1 February 2007 (UTC) | [CC BY-SA 2.5](https://creativecommons.org/licenses/by-sa/2.5) |
| `assets/timbres/baixo-palheta.jpg` | Baixo Palheta | [0 headstock of Yamaha fretless bass guitar RBX250 F.jpg](https://commons.wikimedia.org/wiki/File:0_headstock_of_Yamaha_fretless_bass_guitar_RBX250_F.jpg) | Elmschrat | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/baixo-synth.jpg` | Baixo Synth | [Minimoog.JPG](https://commons.wikimedia.org/wiki/File:Minimoog.JPG) | Krash | Public domain |
| `assets/timbres/caixinha.jpg` | Caixinha de Música | ["The Common Chiffchaff" - DPLA - 1b695a61c07becc0ed8e2e5a16cdc4df (page 1).jpg](https://commons.wikimedia.org/wiki/File:%22The_Common_Chiffchaff%22_-_DPLA_-_1b695a61c07becc0ed8e2e5a16cdc4df_(page_1).jpg) | President (2009-2017 : Obama). Office of the Staff Secretary. Office of Presidential Correspondence. Gift Office. (1/20/2009 - 1/20/2017) | Public domain |
| `assets/timbres/celesta.jpg` | Celesta | [Celesta Schiedmayer MIM 1592.jpg](https://commons.wikimedia.org/wiki/File:Celesta_Schiedmayer_MIM_1592.jpg) | Museumsinsulaner | Public domain |
| `assets/timbres/clavinet.jpg` | Clavinet | [Clavinet d6.jpg](https://commons.wikimedia.org/wiki/File:Clavinet_d6.jpg) | (ver a página da foto) | [CC BY-SA 3.0](http://creativecommons.org/licenses/by-sa/3.0/) |
| `assets/timbres/coral.jpg` | Coral | [Howard Gospel Choir 2 (4369636665).jpg](https://commons.wikimedia.org/wiki/File:Howard_Gospel_Choir_2_(4369636665).jpg) | US Embassy Sweden | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/cordas.jpg` | Cordas | [Details of an old Violin (33039808838).jpg](https://commons.wikimedia.org/wiki/File:Details_of_an_old_Violin_(33039808838).jpg) | Dejan Krsmanovic | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/cordas-lentas.jpg` | Cordas Lentas | [Old Wooden Cello - Flickr - dejankrsmanovic.jpg](https://commons.wikimedia.org/wiki/File:Old_Wooden_Cello_-_Flickr_-_dejankrsmanovic.jpg) | Dejan Krsmanovic | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/cordas-synth.jpg` | Cordas Synth | [SolinaStringEnsemble 02.JPG](https://commons.wikimedia.org/wiki/File:SolinaStringEnsemble_02.JPG) | MFbay | Public domain |
| `assets/timbres/guitarra-chorus.jpg` | Guitarra com Chorus | [1958 Fender Stratocaster.jpg](https://commons.wikimedia.org/wiki/File:1958_Fender_Stratocaster.jpg) | User:Lightburst | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/guitarra-distorcida.jpg` | Guitarra Distorcida | [Marshall 5005 Lead 12 Mini-stack White.jpg](https://commons.wikimedia.org/wiki/File:Marshall_5005_Lead_12_Mini-stack_White.jpg) | Oldangelmidnight from Northampton, MA | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/guitarra-jazz.jpg` | Guitarra Jazz | [Jazz guitarist Robert Kessler at Buetzer Swing Festival.jpg](https://commons.wikimedia.org/wiki/File:Jazz_guitarist_Robert_Kessler_at_Buetzer_Swing_Festival.jpg) | Stefan Barsch | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/guitarra-limpa.jpg` | Guitarra Limpa | [Fender American Telecaster with humbucker neck pickup & Callaham bridge (2016-12-31 17.31.59 by Interested Bystandr).jpg](https://commons.wikimedia.org/wiki/File:Fender_American_Telecaster_with_humbucker_neck_pickup_%26_Callaham_bridge_(2016-12-31_17.31.59_by_Interested_Bystandr).jpg) | interestedbystandr | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/guitarra-overdrive.jpg` | Guitarra Overdrive | [Gibson Custom Shop Les Paul Custom Florentine (vertical).jpg](https://commons.wikimedia.org/wiki/File:Gibson_Custom_Shop_Les_Paul_Custom_Florentine_(vertical).jpg) | Florentine les paul.jpg: Ma guitareThe original uploader was commons at brutaltruth Wikimedia Commons. derivative work: User:Clusternote | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/honky-tonk.jpg` | Piano Honky-tonk | [Shaniko Ghost Town, OR 8-30-13zt (10251068875).jpg](https://commons.wikimedia.org/wiki/File:Shaniko_Ghost_Town,_OR_8-30-13zt_(10251068875).jpg) | inkknife_2000 (7.5 million views +) | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/kalimba.jpg` | Kalimba | [Earthsound Kalimba.jpg](https://commons.wikimedia.org/wiki/File:Earthsound_Kalimba.jpg) | １３２人目 at Japanese Wikipedia | [CC BY-SA 3.0](http://creativecommons.org/licenses/by-sa/3.0/) |
| `assets/timbres/marimba.jpg` | Marimba | [Marimba-Antonko-AMC12.jpg](https://commons.wikimedia.org/wiki/File:Marimba-Antonko-AMC12.jpg) | Vassia Atanassova - Spiritia | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/orgao-hammond.jpg` | Órgão Hammond | [Hammond-museum-1.png](https://commons.wikimedia.org/wiki/File:Hammond-museum-1.png) | Фіксер | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/orgao-percussivo.jpg` | Órgão Percussivo | [Bristol HammondB3.png](https://commons.wikimedia.org/wiki/File:Bristol_HammondB3.png) | Ncopeland at English Wikipedia | Public domain |
| `assets/timbres/orgao-rock.jpg` | Órgão Rock | [Fender Vibratone.jpg](https://commons.wikimedia.org/wiki/File:Fender_Vibratone.jpg) | Jurch | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/orgao-tubos.jpg` | Órgão de Tubos | [Cathedral of Albi - Nave and Organ - 7029.jpg](https://commons.wikimedia.org/wiki/File:Cathedral_of_Albi_-_Nave_and_Organ_-_7029.jpg) | PierreSelim | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0) |
| `assets/timbres/orgao-tubos-2.jpg` | Órgão de Tubos 2 | [Organ-pipes-5.jpg](https://commons.wikimedia.org/wiki/File:Organ-pipes-5.jpg) | Tucker501 | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/pad-atmosfera.jpg` | Pad Atmosfera | [Aurora Borealis NO.JPG](https://commons.wikimedia.org/wiki/File:Aurora_Borealis_NO.JPG) | Rafal Konieczny | [CC BY 2.5](https://creativecommons.org/licenses/by/2.5) |
| `assets/timbres/pad-chuva-gelo.jpg` | Pad Chuva de Gelo | [Ice formations 2.jpg](https://commons.wikimedia.org/wiki/File:Ice_formations_2.jpg) | W.carter | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/pad-cristal.jpg` | Pad Cristal | [Quartz-153471.jpg](https://commons.wikimedia.org/wiki/File:Quartz-153471.jpg) | Robert M. Lavinsky | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/pad-halo.jpg` | Pad Halo | ["Halo, World!" (D5D1512-CC).tiff](https://commons.wikimedia.org/wiki/File:%22Halo,_World!%22_(D5D1512-CC).tiff) | ESO/G. Hüdepohl (atacamaphoto.com) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0) |
| `assets/timbres/pad-orgao.jpg` | Pad Órgão | [Rotary Speaker Cabinet (by Ralph Hogaboom) - rotor unit made of Styrofoam.jpg](https://commons.wikimedia.org/wiki/File:Rotary_Speaker_Cabinet_(by_Ralph_Hogaboom)_-_rotor_unit_made_of_Styrofoam.jpg) | Ralph Hogaboom | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/pad-orquestra.jpg` | Pad Orquestra | [Alborz Symphony Orchestra concert at Milad Hall in 2015 (08).jpg](https://commons.wikimedia.org/wiki/File:Alborz_Symphony_Orchestra_concert_at_Milad_Hall_in_2015_(08).jpg) | Hossein Razaqnejad | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0) |
| `assets/timbres/pad-polysynth.jpg` | Pad Polysynth | [DSI Prophet '08 - left side view - Orlando Synthesizer Meetup Dec 2016 (2016-12-04 (28) by Mac Rutan).png](https://commons.wikimedia.org/wiki/File:DSI_Prophet_%2708_-_left_side_view_-_Orlando_Synthesizer_Meetup_Dec_2016_(2016-12-04_(28)_by_Mac_Rutan).png) | Mac Rutan from Oviedo, FL, U.S.A. | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/pad-quente.jpg` | Pad Quente | [Colorful sky with orange clouds reflecting in the water of a paddy field, at sunset, Vang Vieng, Laos.jpg](https://commons.wikimedia.org/wiki/File:Colorful_sky_with_orange_clouds_reflecting_in_the_water_of_a_paddy_field,_at_sunset,_Vang_Vieng,_Laos.jpg) | Basile Morin | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/pad-sweep.jpg` | Pad Sweep | [036 Milky Way during Perseids seen from Oeschinensee with water reflections Photo by Giles Laurent.jpg](https://commons.wikimedia.org/wiki/File:036_Milky_Way_during_Perseids_seen_from_Oeschinensee_with_water_reflections_Photo_by_Giles_Laurent.jpg) | Giles Laurent | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/pad-vidro.jpg` | Pad Vidro | [Glasharmonika Colmar.jpg](https://commons.wikimedia.org/wiki/File:Glasharmonika_Colmar.jpg) | -jkb- | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/pad-vozes.jpg` | Pad Vozes | [BLW Stained Glass - Annunciation to St Anne.jpg](https://commons.wikimedia.org/wiki/File:BLW_Stained_Glass_-_Annunciation_to_St_Anne.jpg) | David Jackson | [CC BY-SA 2.0 uk](https://creativecommons.org/licenses/by-sa/2.0/uk/deed.en) |
| `assets/timbres/piano-brilhante.jpg` | Piano Brilhante | [Berlin- Grand piano and French horn at the Konzerthaus - 4250.jpg](https://commons.wikimedia.org/wiki/File:Berlin-_Grand_piano_and_French_horn_at_the_Konzerthaus_-_4250.jpg) | Jorge Royan | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/piano-cauda.jpg` | Piano de Cauda | [Fritz Dobbert Grand Piano from the 1980's.jpg](https://commons.wikimedia.org/wiki/File:Fritz_Dobbert_Grand_Piano_from_the_1980%27s.jpg) | Vrsooo | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/piano-cp.jpg` | Piano Elétrico (CP) | [Yamaha CP-80 Electric Grand Piano, 88 keys, 1978.jpg](https://commons.wikimedia.org/wiki/File:Yamaha_CP-80_Electric_Grand_Piano,_88_keys,_1978.jpg) | haru__q | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/piano-fm.jpg` | Piano FM (DX) | [YAMAHA DX7.jpg](https://commons.wikimedia.org/wiki/File:YAMAHA_DX7.jpg) | Finnianhughes101 | Public domain |
| `assets/timbres/piano-fm-chorus.jpg` | Piano FM com Chorus | [DX7II-D.jpg](https://commons.wikimedia.org/wiki/File:DX7II-D.jpg) | Niels Heidenreich from Hannover, Germany | [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0) |
| `assets/timbres/rhodes.jpg` | Rhodes | [1977 Rhodes Mark I Suitcase Piano 73-key (serial no. K610578) (2005-01-29 09.27.49 by Daniel Spils).jpg](https://commons.wikimedia.org/wiki/File:1977_Rhodes_Mark_I_Suitcase_Piano_73-key_(serial_no._K610578)_(2005-01-29_09.27.49_by_Daniel_Spils).jpg) | Daniel Spils from Seattle, USA | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/rhodes-chorus.jpg` | Rhodes com Chorus | [(The Rhodes piano) (Photography by David Adam Kess) interior (an electric piano invented by Harold Rhodes).jpg](https://commons.wikimedia.org/wiki/File:(The_Rhodes_piano)_(Photography_by_David_Adam_Kess)_interior_(an_electric_piano_invented_by_Harold_Rhodes).jpg) | David Adam Kess | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/sinos-tubulares.jpg` | Sinos | [Adams Bass Chimes.jpg](https://commons.wikimedia.org/wiki/File:Adams_Bass_Chimes.jpg) | Xylosmygame / Xylosmygame at en.wikipedia | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0) |
| `assets/timbres/synth-lead.jpg` | Synth Lead | [KORG RK-100S keytar - angled right - 2014 NAMM Show (by Matt Vanacoro).jpg](https://commons.wikimedia.org/wiki/File:KORG_RK-100S_keytar_-_angled_right_-_2014_NAMM_Show_(by_Matt_Vanacoro).jpg) | Matt Vanacoro | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/vibrafone.jpg` | Vibrafone | [RCAStudioB Vibraphone 1.jpg](https://commons.wikimedia.org/wiki/File:RCAStudioB_Vibraphone_1.jpg) | Cliff from I now live in Arlington, VA (Outside Washington DC), USA | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/violao-12.jpg` | Violão 12 Cordas | [Framus 12-string acoustic guitar - headstock - Sir Theo, Belgaum, India (2011-11-23 08.11.05 by julian correa).jpg](https://commons.wikimedia.org/wiki/File:Framus_12-string_acoustic_guitar_-_headstock_-_Sir_Theo,_Belgaum,_India_(2011-11-23_08.11.05_by_julian_correa).jpg) | julian correa from belgaum cantonement, india | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0) |
| `assets/timbres/violao-aco.jpg` | Violão Aço | [00 Walden Acoustic Guitar D310e body.jpg](https://commons.wikimedia.org/wiki/File:00_Walden_Acoustic_Guitar_D310e_body.jpg) | Elmschrat | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0) |
| `assets/timbres/violao-nylon.jpg` | Violão Nylon | [Classical Guitar two views-cropped.jpg](https://commons.wikimedia.org/wiki/File:Classical_Guitar_two_views-cropped.jpg) | The original uploader was Piero Sagnibene at Italian Wikipedia. | [CC BY-SA 2.0 de](https://creativecommons.org/licenses/by-sa/2.0/de/deed.en) |

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
