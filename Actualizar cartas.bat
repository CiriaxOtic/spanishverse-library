@echo off
rem Actualiza todo, igual que el boton «Actualizar» del programa (tools\updater.py): cartas e imagenes del sitio
rem oficial, traducciones (propias y las publicadas en GitHub), voces del juego e ilustraciones sin marco.
rem Solo hace falta para quien usa el programa con Python; el .exe se actualiza desde su propio boton.
cd /d "%~dp0"
py -3.13 tools\updater.py
pause
