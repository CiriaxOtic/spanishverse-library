# Spanishverse Library

**Biblioteca de cartas de Shadowverse: Worlds Beyond, en español, para la comunidad latina.**
Programa **libre y gratuito** para Windows: todas las cartas con sus efectos, ambientaciones y preguntas oficiales
traducidas, las voces de cada carta, las ilustraciones sin marco y un armador de mazos con códigos para el juego.

> Hecho **de fans y para fans**, sin fines de lucro. Shadowverse: Worlds Beyond y todo su contenido son © Cygames, Inc.
> Este programa no está afiliado a Cygames y no modifica el juego.

## Qué tiene

- **Todas las cartas** del juego (también las fichas), con la imagen oficial en español cuando existe.
- **Todo en español**: textos oficiales de la versión latina y, para las cartas que todavía no la tienen,
  traducción propia de los efectos, las ambientaciones y las preguntas oficiales, con los términos oficiales.
- **Filtros como los del juego**: clase, costo, tipo, rareza, expansión, tipo de carta (tribu), palabra clave,
  ataque y defensa, formato Rotación / Ilimitado, y búsqueda por texto.
- **«Ver creadoras» y «Ver lo que trae»**: qué cartas pueden crear una carta y qué cartas crea cada una.
- **Glosario** oficial, y el significado de cada palabra clave al pasar el mouse.
- **Voces** de cada carta (normal y evolucionada), sacadas del juego instalado en tu PC.
- **Ilustraciones sin marco** en grande, con zoom.
- **Armador de mazos** con curva de costos, viales y **códigos para importar en el juego**.
- **Se actualiza solo**: cuando sale una expansión, el programa avisa y baja las cartas nuevas con sus imágenes,
  traducciones, voces e ilustraciones.

## Cómo instalarlo

1. Entrá en **[Releases](../../releases/latest)** y bajá `SpanishverseLibrary-<versión>.zip`.
2. Descomprimilo en cualquier carpeta (por ejemplo, Documentos). No hace falta instalar nada más.
3. Abrí **`Spanishverse Library.exe`**.
4. La primera vez, la pantalla de inicio te pide **Descargar todo**: las imágenes de las cartas y las ilustraciones
   (unos 3 GB) y, si tenés el juego en Steam, las voces. Se hace una sola vez; si se corta internet, sigue después desde
   donde quedó. Al terminar ofrece accesos directos en el escritorio y en el menú Inicio.
5. Después de esa primera vez, el programa **funciona sin internet**. Actualizar es opcional.

**Actualizaciones:** el botón **⟳ Actualizar** actualiza todo: las cartas nuevas y también el propio programa (cada
arreglo o mejora publicada acá se instala sola), conservando tus mazos, voces, imágenes y ajustes. No hace falta
volver a bajar nada a mano.

**Requisitos:** Windows 10 u 11 e internet para actualizar. Para las voces, tener Shadowverse: Worlds Beyond
instalado en Steam (sin el juego, todo lo demás funciona igual).

## Manual

En el archivo **[Manual de Spanishverse Library.pdf](docs/Manual%20de%20Spanishverse%20Library.pdf)** está
explicada cada parte del programa, con capturas, y qué es cada archivo de la carpeta.

## Para quien quiera colaborar

El programa está hecho en Python (tkinter). Con Python 3.13 y `pip install numpy pillow soundcard` se puede abrir
`Spanishverse Library.pyw` directamente. Las traducciones propias están en `traducciones/` y las correcciones a
mano en `traducciones/correcciones.json`: cada copia del programa las baja de este repositorio al actualizar.

## Licencia

Código bajo licencia MIT (ver [LICENCIA.txt](LICENCIA.txt)). El contenido del juego es de Cygames, Inc.
Ilustraciones: de sus ilustradores (figuran en cada carta). Gracias a WBGDB por las ilustraciones sin marco y a
vgmstream por la conversión de audio.

**Este programa es y va a ser siempre gratis. Si alguien te lo vendió, te estafaron.**
