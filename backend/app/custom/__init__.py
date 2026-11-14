"""Código do fork gabriel (ver custom/CUSTOMIZATIONS.md).

Nada aqui é importado pelo upstream. A aplicação do fork é montada por
``backend.app.custom.asgi`` (importa ``backend.app.main.app`` e registra os
routers nossos), que é o que a imagem ``bambuddy-gabriel`` executa.
"""
