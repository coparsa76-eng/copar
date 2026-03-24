#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web - Versão Completa Corrigida
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configurações
app.secret_key = os.environ.get('SECRET_KEY', 'copar-secret-key-2024')

app.config.update(
    SESSION_COOKIE_SECURE=False,  # True em produção com HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1)
)

# String de conexão do banco
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require')

# ========== FUNÇÕES DO BANCO ==========

def conectar_banco():
    """Conecta ao banco de dados PostgreSQL"""
    try:
        conn = psycopg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Erro de conexão com banco: {e}")
        return None

def buscar_produtor_por_matricula(matricula):
    """Busca o produtor pela matrícula"""
    
    # ACESSO ESPECIAL: Se for copar10, retorna acesso ao formulário de entrada
    if matricula.lower() == 'copar10':
        return {
            'id': 9999,
            'nome': 'Administrador - Registro de Entrada',
            'matricula': 'copar10',
            'especial': True
        }
    
    conn = conectar_banco()
    if not conn:
        logger.error("Não foi possível conectar ao banco")
        return None
    
    try:
        cursor = conn.cursor()
        # Buscar por matrícula exata
        cursor.execute("""
            SELECT id, nome, matricula 
            FROM produtores 
            WHERE matricula = %s
        """, (matricula,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if produtor:
            logger.info(f"Produtor encontrado: ID={produtor[0]}, Nome={produtor[1]}, Matrícula={produtor[2]}")
            return {
                'id': produtor[0],
                'nome': produtor[1],
                'matricula': produtor[2],
                'especial': False
            }
        else:
            logger.warning(f"Produtor com matrícula {matricula} não encontrado")
            return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None

def buscar_produtor_por_id(produtor_id):
    """Busca produtor pelo ID"""
    conn = conectar_banco()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, matricula FROM produtores WHERE id = %s", (produtor_id,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if produtor:
            return {
                'id': produtor[0],
                'nome': produtor[1],
                'matricula': produtor[2]
            }
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor por ID: {e}")
        return None

def buscar_produtores_por_termo(termo):
    """Busca produtores por nome ou matrícula"""
    conn = conectar_banco()
    if not conn:
        logger.error("Não foi possível conectar ao banco para busca")
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT matricula, nome, id 
            FROM produtores 
            WHERE matricula ILIKE %s OR nome ILIKE %s
            ORDER BY nome
            LIMIT 20
        """, (f'%{termo}%', f'%{termo}%'))
        
        produtores = []
        for row in cursor.fetchall():
            produtores.append({
                'matricula': row[0],
                'nome': row[1],
                'id': row[2]
            })
        
        cursor.close()
        conn.close()
        logger.info(f"Busca por '{termo}' retornou {len(produtores)} resultados")
        return produtores
    except Exception as e:
        logger.error(f"Erro ao buscar produtores: {e}")
        return []

def registrar_entrada_estoque(produtor_id, tipo_alho, classe, peso, local_armazenamento, horas_banca=0):
    """Registra entrada no estoque"""
    conn = conectar_banco()
    if not conn:
        return False, "Erro de conexão com o banco"
    
    try:
        cursor = conn.cursor()
        
        # Registrar entrada
        cursor.execute("""
            INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_armazenamento, horas_banca)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (produtor_id, tipo_alho, classe, peso, local_armazenamento, horas_banca))
        
        entrada_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Entrada registrada: ID {entrada_id}, Produtor {produtor_id}, {peso}Kg de {tipo_alho} {classe}")
        return True, entrada_id
        
    except Exception as e:
        logger.error(f"Erro ao registrar entrada: {e}")
        if conn:
            conn.rollback()
        return False, str(e)

# ========== ROTAS ==========

@app.route('/')
def index():
    """Página inicial"""
    if 'produtor_id' in session:
        if session.get('acesso_especial'):
            return redirect(url_for('registro_entrada'))
        return redirect(url_for('produtor'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Tela de login"""
    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip()
        
        if not matricula:
            return render_template('login.html', erro='Digite sua matrícula')
        
        produtor = buscar_produtor_por_matricula(matricula)
        
        if produtor:
            session['produtor_id'] = produtor['id']
            session['produtor_nome'] = produtor['nome']
            session['produtor_matricula'] = produtor['matricula']
            session['acesso_especial'] = produtor.get('especial', False)
            
            if session['acesso_especial']:
                return redirect(url_for('registro_entrada'))
            else:
                return redirect(url_for('produtor'))
        else:
            return render_template('login.html', erro='Matrícula não encontrada')
    
    return render_template('login.html', erro=None)

@app.route('/produtor')
def produtor():
    """Tela normal do produtor"""
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    
    # Importar funções da tela do produtor (você precisa criar essas funções)
    return render_template('produtor.html', nome=session.get('produtor_nome', ''))

@app.route('/registro-entrada')
def registro_entrada():
    """Tela de registro de entrada de alho"""
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('registro_entrada.html')

@app.route('/api/buscar-produtor', methods=['POST'])
def api_buscar_produtor():
    """API para buscar produtor por matrícula"""
    data = request.get_json()
    matricula = data.get('matricula', '').strip()
    
    if not matricula:
        return jsonify({'encontrado': False, 'mensagem': 'Matrícula não informada'})
    
    logger.info(f"Buscando produtor com matrícula: {matricula}")
    
    conn = conectar_banco()
    if not conn:
        return jsonify({'encontrado': False, 'mensagem': 'Erro de conexão com o banco'})
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, matricula FROM produtores WHERE matricula = %s", (matricula,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if produtor:
            logger.info(f"Produtor encontrado: ID={produtor[0]}, Nome={produtor[1]}")
            return jsonify({
                'encontrado': True,
                'id': produtor[0],
                'matricula': produtor[2],
                'nome': produtor[1]
            })
        else:
            logger.warning(f"Produtor não encontrado com matrícula: {matricula}")
            return jsonify({'encontrado': False, 'mensagem': 'Produtor não encontrado'})
            
    except Exception as e:
        logger.error(f"Erro na API de busca: {e}")
        return jsonify({'encontrado': False, 'mensagem': str(e)})

@app.route('/api/buscar-produtores', methods=['GET'])
def api_buscar_produtores():
    """API para autocomplete de produtores"""
    termo = request.args.get('termo', '').strip()
    
    if len(termo) < 1:
        return jsonify([])
    
    logger.info(f"Buscando produtores por termo: {termo}")
    produtores = buscar_produtores_por_termo(termo)
    return jsonify(produtores)

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    """API para salvar registro de entrada de alho"""
    data = request.get_json()
    
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400
    
    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local = data.get('local', 'Classificação')
    detalhes = data.get('detalhes', [])
    
    logger.info(f"Recebendo entrada: produtor_id={produtor_id}, tipo={tipo_alho}, local={local}")
    
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum peso registrado'})
    
    # Mapeamento das classes
    classes_mapeamento = {
        "INDÚSTRIA": "Indústria",
        "DEBULHADO": "Debulhado",
        "TIPO 2": "Classe 2",
        "TIPO 3": "Classe 3",
        "TIPO 4": "Classe 4",
        "TIPO 5": "Classe 5",
        "TIPO 6": "Classe 6",
        "TIPO 7": "Classe 7"
    }
    
    resultados = []
    erros = []
    peso_total = 0
    
    for item in detalhes:
        classe_origem = item.get('classe')
        peso = item.get('peso', 0)
        
        if peso > 0:
            classe_destino = classes_mapeamento.get(classe_origem, classe_origem)
            peso_total += peso
            
            sucesso, resultado = registrar_entrada_estoque(
                produtor_id=produtor_id,
                tipo_alho=tipo_alho,
                classe=classe_destino,
                peso=peso,
                local_armazenamento=local,
                horas_banca=0
            )
            
            if sucesso:
                resultados.append({
                    'classe': classe_origem,
                    'peso': peso,
                    'entrada_id': resultado
                })
            else:
                erros.append({
                    'classe': classe_origem,
                    'peso': peso,
                    'erro': resultado
                })
    
    if erros:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro ao salvar alguns itens: {erros[0]["erro"]}',
            'sucessos': resultados,
            'erros': erros
        }), 207
    
    return jsonify({
        'sucesso': True,
        'mensagem': f'Entrada registrada com sucesso! Total: {peso_total} Kg',
        'registros': resultados
    })

@app.route('/logout')
def logout():
    """Sair do sistema"""
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
