#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COPAR Web - Versão Completa
Com formulário de entrada de alho para copar10
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import psycopg
import os
import logging
from datetime import datetime, timedelta
from functools import wraps
from decimal import Decimal

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ========== CONFIGURAÇÕES DE SEGURANÇA ==========
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

app.config.update(
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_SECURE', 'False').lower() == 'true',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1)
)

# String de conexão do banco
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_Bp1AmUEoX7ui@ep-summer-haze-a8lxhx5j-pooler.eastus2.azure.neon.tech/neondb?sslmode=require')

# ========== CONSTANTES (mesmas do sistema Tkinter) ==========
TIPOS_ALHO = ['Ito', 'Chonan', 'São Valentim', 'Tratado', 'Semente']
CLASSES_ESTOQUE = ["Indústria", "Classe 2", "Classe 3", "Classe 4", "Classe 5", "Classe 6", "Classe 7"]
LOCAIS_ESTOQUE = ["Classificação", "banca", "toletagem"]

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
        return None
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, nome, matricula 
            FROM produtores 
            WHERE matricula = %s
        """, (matricula,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if produtor:
            return {
                'id': produtor[0],
                'nome': produtor[1],
                'matricula': produtor[2],
                'especial': False
            }
        return None
    except Exception as e:
        logger.error(f"Erro ao buscar produtor: {e}")
        return None

def registrar_entrada_estoque(produtor_id, tipo_alho, classe, peso, local_armazenamento, horas_banca=0):
    """Registra entrada no estoque - MESMA FUNÇÃO DO TKINTER"""
    conn = conectar_banco()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # Se não for Classificação Inicial, precisa verificar estoque
        if local_armazenamento != "Classificação":
            # Verificar se há estoque suficiente na classificação
            cursor.execute("""
                SELECT COALESCE(SUM(peso), 0) 
                FROM estoque 
                WHERE produtor_id = %s 
                AND tipo_alho = %s 
                AND classe = %s 
                AND local_armazenamento = 'Classificação'
                AND peso > 0
            """, (produtor_id, tipo_alho, classe))
            
            estoque_classificacao = Decimal(str(cursor.fetchone()[0] or 0))
            
            if estoque_classificacao < Decimal(str(peso)):
                conn.close()
                return False, f"Estoque insuficiente na Classificação! Disponível: {estoque_classificacao:.2f}Kg, Necessário: {peso:.2f}Kg"
            
            # Dar baixa na classificação
            peso_restante = Decimal(str(peso))
            cursor.execute("""
                SELECT id, peso FROM estoque 
                WHERE produtor_id = %s 
                AND tipo_alho = %s 
                AND classe = %s 
                AND local_armazenamento = 'Classificação'
                AND peso > 0
                ORDER BY data_registro
            """, (produtor_id, tipo_alho, classe))
            
            entradas = cursor.fetchall()
            
            for entrada_id, peso_atual in entradas:
                if peso_restante <= 0:
                    break
                    
                peso_atual_dec = Decimal(str(peso_atual))
                if peso_restante >= peso_atual_dec:
                    cursor.execute("DELETE FROM estoque WHERE id = %s", (entrada_id,))
                    peso_restante -= peso_atual_dec
                else:
                    novo_peso = peso_atual_dec - peso_restante
                    cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s", (float(novo_peso), entrada_id))
                    peso_restante = 0
        
        # Registrar entrada no novo local
        cursor.execute("""
            INSERT INTO estoque (produtor_id, tipo_alho, classe, peso, local_armazenamento, horas_banca)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (produtor_id, tipo_alho, classe, peso, local_armazenamento, horas_banca))
        
        entrada_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Entrada registrada: ID {entrada_id}, Produtor {produtor_id}, {peso}Kg de {tipo_alho} {classe} em {local_armazenamento}")
        return True, entrada_id
        
    except Exception as e:
        logger.error(f"Erro ao registrar entrada: {e}")
        if conn:
            conn.rollback()
        return False, str(e)

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
        # Dados de demonstração
        return [
            {"matricula": "283", "nome": "Odair Garallo"},
            {"matricula": "284", "nome": "João da Silva"},
            {"matricula": "285", "nome": "Manoel Ferreira"},
            {"matricula": "286", "nome": "Sebastião Alves"},
            {"matricula": "287", "nome": "Antônio Carlos"},
            {"matricula": "288", "nome": "Francisco Oliveira"},
            {"matricula": "289", "nome": "José Roberto"},
            {"matricula": "290", "nome": "Luiz Henrique"}
        ]
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT matricula, nome 
            FROM produtores 
            WHERE matricula ILIKE %s OR nome ILIKE %s
            ORDER BY nome
            LIMIT 20
        """, (f'%{termo}%', f'%{termo}%'))
        
        produtores = []
        for row in cursor.fetchall():
            produtores.append({
                'matricula': row[0],
                'nome': row[1]
            })
        
        cursor.close()
        conn.close()
        return produtores
    except Exception as e:
        logger.error(f"Erro ao buscar produtores: {e}")
        return []

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
    
    if session.get('acesso_especial'):
        return redirect(url_for('registro_entrada'))
    
    # Importar funções para a tela do produtor
    from app_produtor import buscar_estoque, buscar_vendas, calcular_saldos
    
    produtor_id = session['produtor_id']
    produtor_nome = session['produtor_nome']
    
    estoque = buscar_estoque(produtor_id)
    vendas = buscar_vendas(produtor_id)
    total_recebido, total_a_receber = calcular_saldos(vendas)
    
    return render_template('produtor.html',
                         nome=produtor_nome,
                         estoque=estoque,
                         vendas=vendas,
                         total_recebido=total_recebido,
                         total_a_receber=total_a_receber)

@app.route('/registro-entrada')
def registro_entrada():
    """Tela de registro de entrada de alho (acesso especial)"""
    if 'produtor_id' not in session:
        return redirect(url_for('login'))
    
    if not session.get('acesso_especial'):
        flash('Acesso não autorizado.', 'erro')
        return redirect(url_for('produtor'))
    
    return render_template('registro_entrada.html', 
                         tipos_alho=TIPOS_ALHO,
                         classes_estoque=CLASSES_ESTOQUE,
                         locais_estoque=LOCAIS_ESTOQUE)

@app.route('/api/buscar-produtor', methods=['POST'])
def api_buscar_produtor():
    """API para buscar produtor por matrícula"""
    data = request.get_json()
    matricula = data.get('matricula', '')
    
    conn = conectar_banco()
    if not conn:
        return jsonify({'encontrado': False, 'mensagem': 'Erro de conexão'})
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome, matricula FROM produtores WHERE matricula = %s", (matricula,))
        produtor = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if produtor:
            return jsonify({
                'encontrado': True,
                'id': produtor[0],
                'matricula': produtor[2],
                'nome': produtor[1]
            })
        else:
            return jsonify({'encontrado': False, 'mensagem': 'Produtor não encontrado'})
    except Exception as e:
        logger.error(f"Erro na API: {e}")
        return jsonify({'encontrado': False, 'mensagem': str(e)})

@app.route('/api/buscar-produtores', methods=['GET'])
def api_buscar_produtores():
    """API para autocomplete de produtores"""
    termo = request.args.get('termo', '')
    produtores = buscar_produtores_por_termo(termo)
    return jsonify(produtores)

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    """API para salvar registro de entrada de alho"""
    data = request.get_json()
    
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400
    
    # Validar dados obrigatórios
    produtor_id = data.get('produtor_id')
    tipo_alho = data.get('tipo_alho')
    local = data.get('local', 'Classificação')
    peso_total = data.get('peso_total', 0)
    
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    
    if peso_total <= 0:
        return jsonify({'sucesso': False, 'mensagem': 'Peso total deve ser maior que zero'})
    
    # Processar cada classe/tipo
    resultados = []
    erros = []
    
    # Mapeamento das classes para o formato do sistema
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
    
    for item in data.get('detalhes', []):
        classe_origem = item.get('classe')
        peso = item.get('peso', 0)
        
        if peso > 0:
            classe_destino = classes_mapeamento.get(classe_origem, classe_origem)
            
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
            'mensagem': f'Erro ao salvar alguns itens: {erros}',
            'sucessos': resultados,
            'erros': erros
        }), 207
    
    # Registrar log da operação
    logger.info(f"Entrada registrada: Produtor {produtor_id}, Tipo {tipo_alho}, Local {local}, Peso total {peso_total}Kg")
    
    return jsonify({
        'sucesso': True,
        'mensagem': f'Entrada registrada com sucesso! Total: {peso_total}Kg',
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
