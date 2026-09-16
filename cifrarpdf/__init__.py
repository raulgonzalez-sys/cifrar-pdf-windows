"""Cifrar PDF (FISAT) para Windows.

Backend de la herramienta: vigila carpetas del Escritorio y cifra con
contraseña (AES-256) los PDF que se sueltan en ellas.

La GUI (gui.py) es solo un frontend y habla con este backend por los
subcomandos «--gui-*» de cifrarpdf.cli, exactamente el mismo contrato que usa
el backend bash de los puestos Debian.
"""

__version__ = "1.1.0"
