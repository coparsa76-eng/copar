#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'copar-secret-key-2024')

app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8)
)

DATABASE_URL = os.environ.get('DATABASE_URL')

# ───────────────── CONFIG ─────────────────

MAPEAMENTO_LOCAL = {
    'Classificação': 'Classificação',
    'classificacao': 'Classificação',
    'banca': 'Banca',
    'Banca': 'Banca',
    'toletagem': 'Toletagem',
    'Toletagem': 'Toletagem',
}

CLASSES_MAP = {
    "INDÚSTRIA": "Indústria",
    "TIPO 2": "Classe 2",
    "TIPO 3": "Classe 3",
    "TIPO 4": "Classe 4",
    "TIPO 5": "Classe 5",
    "TIPO 6": "Classe 6",
    "TIPO 7": "Classe 7",
}

VALOR_HORA_BANCA = 16.0

USUARIOS_ESPECIAIS = {
    'copar10entrada': {'id': 9991, 'nome': 'Classificação', 'tipo': 'classificacao'},
    'copar22banca': {'id': 9992, 'nome': 'Banca', 'tipo': 'banca'},
    'copar33toletagem': {'id': 9993, 'nome': 'Toletagem', 'tipo': 'toletagem'},
    'glh': {'id': 8888, 'nome': 'Gerente', 'tipo': 'gerente'},
    'copar10': {'id': 9999, 'nome': 'Admin', 'tipo': 'superadmin'},
}

# ───────────────── BANCO ─────────────────

def conectar_banco():
    try:
        return psycopg.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"Erro conexão: {e}")
        return None

# ───────────────── FIFO GLOBAL ─────────────────

def retirar_fifo_global(cursor, produtor_id, tipo_alho, local, peso_total):
    cursor.execute("""
        SELECT id, classe, peso FROM estoque
        WHERE produtor_id=%s AND tipo_alho=%s
          AND local_estoque=%s AND peso>0
        ORDER BY data_registro
    """, (produtor_id, tipo_alho, local))

    restante = peso_total

    for eid, classe, epeso in cursor.fetchall():
        if restante <= 0:
            break

        epeso = float(epeso)
        retirar = min(restante, epeso)

        if retirar >= epeso:
            cursor.execute("DELETE FROM estoque WHERE id=%s", (eid,))
        else:
            cursor.execute(
                "UPDATE estoque SET peso=%s WHERE id=%s",
                (epeso - retirar, eid)
            )

        restante -= retirar

# ───────────────── AUTENTICAÇÃO ─────────────────

def buscar_produtor(matricula):
    if matricula in USUARIOS_ESPECIAIS:
        return USUARIOS_ESPECIAIS[matricula]

    conn = conectar_banco()
    if not conn:
        return None

    cursor = conn.cursor()
    cursor.execute("SELECT id, nome FROM produtores WHERE matricula=%s", (matricula,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {'id': row[0], 'nome': row[1], 'tipo': 'produtor'}
    return None

# ───────────────── CONSULTAS ─────────────────

def buscar_estoque(produtor_id):
    conn = conectar_banco()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tipo_alho, classe, SUM(peso)
        FROM estoque
        WHERE produtor_id=%s AND peso>0
        GROUP BY tipo_alho, classe
    """, (produtor_id,))

    dados = [{'tipo': r[0], 'classe': r[1], 'peso': float(r[2])} for r in cursor.fetchall()]
    conn.close()
    return dados

# ───────────────── ROTAS ─────────────────

@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    return redirect('/dashboard')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        matricula = request.form.get('matricula')
        user = buscar_produtor(matricula)

        if user:
            session['user'] = user
            return redirect('/')
        return render_template('login.html', erro="Login inválido")

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')

    tipo = session['user']['tipo']

    if tipo == 'produtor':
        estoque = buscar_estoque(session['user']['id'])
        return render_template('produtor.html', estoque=estoque)

    if tipo == 'gerente':
        return render_template('gerente.html')

    return render_template('registro_entrada.html', valor_hora=VALOR_HORA_BANCA)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ───────────────── API PRINCIPAL ─────────────────

@app.route('/api/salvar-entrada', methods=['POST'])
def salvar_entrada():
    data = request.get_json()

    produtor_id = data['produtor_id']
    tipo_alho = data['tipo_alho']
    origem = MAPEAMENTO_LOCAL.get(data['local_origem'])
    destino = MAPEAMENTO_LOCAL.get(data['local'])
    detalhes = data['detalhes']

    itens_classe = [d for d in detalhes if d['tipo'] in ('classe', 'industria')]
    itens_quebra = [d for d in detalhes if d['tipo'] == 'quebra']

    peso_classes = sum(float(d['peso']) for d in itens_classe)
    peso_quebra = sum(float(d['peso']) for d in itens_quebra)

    total_saida = peso_classes + peso_quebra

    conn = conectar_banco()
    cursor = conn.cursor()

    # validar saldo total
    cursor.execute("""
        SELECT COALESCE(SUM(peso),0)
        FROM estoque
        WHERE produtor_id=%s AND tipo_alho=%s AND local_estoque=%s
    """, (produtor_id, tipo_alho, origem))

    saldo = float(cursor.fetchone()[0])

    if saldo < total_saida:
        return jsonify({'sucesso': False, 'mensagem': 'Saldo insuficiente'})

    # retirar tudo da origem
    retirar_fifo_global(cursor, produtor_id, tipo_alho, origem, total_saida)

    # inserir destino
    for item in itens_classe:
        classe_ui = item['classe']

        if classe_ui == "INDÚSTRIA":
            classe = "Indústria"
        else:
            classe = CLASSES_MAP.get(classe_ui)

        cursor.execute("""
            INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_estoque)
            VALUES (%s,%s,%s,%s,%s)
        """, (produtor_id, tipo_alho, classe, item['peso'], destino))

    # registrar perda
    if peso_quebra > 0:
        cursor.execute("""
            INSERT INTO perdas
            (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (produtor_id, tipo_alho, "Quebra", peso_quebra, origem, "Perda real"))

    conn.commit()
    conn.close()

    return jsonify({'sucesso': True, 'mensagem': 'Movimentação registrada corretamente'})

# ───────────────── MAIN ─────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
