#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SUBSTITUIR em app.py:
- a função registrar_movimentacao
- a rota api_salvar_entrada

Lógica correta do fluxo Banca/Toletagem:
  Origem tinha X kg.
  O operador pesa o resultado:
    • TIPO 2…7  → entram no estoque do DESTINO como classe normal
    • Indústria → entra no estoque do DESTINO como classe "Indústria"
    • Quebra    → é PERDA REAL (sujeira, alhos ruins). Sai da origem e vai
                  para a tabela `perdas`. NÃO entra em nenhum destino.
  Total retirado da origem = soma(classes) + indústria + quebra
"""

# Importações necessárias (assumindo que estas variáveis/funções existem globalmente ou são importadas)
# from seu_modulo_de_conexao import conectar_banco
# from seu_modulo_de_mapeamento import MAPEAMENTO_LOCAL, CLASSES_MAP
# import logging
# logger = logging.getLogger(__name__)
# from flask import Flask, request, jsonify, session
# app = Flask(__name__)

# --- Mock de dependências para demonstração ---
# Em um ambiente real, estas seriam importadas ou definidas globalmente.
class MockCursor:
    def __init__(self):
        self.executed_queries = []
        self.fetched_data = []
        self.last_insert_id = None

    def execute(self, query, params=None):
        self.executed_queries.append((query, params))
        # Simula retorno para SELECT
        if "SELECT COALESCE(SUM(peso), 0)" in query:
            self.fetched_data = [(0.0,)] # Saldo inicial
        elif "SELECT id, peso FROM estoque" in query:
            self.fetched_data = [(1, 100.0), (2, 50.0)] # Simula itens no estoque
        elif "SELECT id, classe, peso FROM estoque" in query:
            self.fetched_data = [(1, 'TIPO 2', 100.0), (2, 'TIPO 4', 50.0)] # Simula itens no estoque
        elif "RETURNING id" in query:
            self.last_insert_id = 101 # Simula ID gerado
            self.fetched_data = [(self.last_insert_id,)]
        else:
            self.fetched_data = [] # Para INSERT/UPDATE/DELETE

    def fetchone(self):
        return self.fetched_data[0] if self.fetched_data else None

    def fetchall(self):
        return self.fetched_data

    def close(self):
        pass

class MockConnection:
    def __init__(self):
        self.closed = False
        self.transaction_active = False

    def cursor(self):
        if self.closed:
            raise Exception("Connection is closed")
        self.transaction_active = True
        return MockCursor()

    def commit(self):
        if self.closed:
            raise Exception("Connection is closed")
        self.transaction_active = False
        # print("DB COMMIT")

    def rollback(self):
        if self.closed:
            raise Exception("Connection is closed")
        self.transaction_active = False
        # print("DB ROLLBACK")

    def close(self):
        self.closed = True
        # print("DB CLOSE")

def conectar_banco():
    # Simula a conexão com o banco de dados
    # Em um ambiente real, esta função retornaria um objeto de conexão real.
    # print("DB CONNECT")
    return MockConnection()

# Mapeamentos e constantes (assumindo que existem)
MAPEAMENTO_LOCAL = {
    "Classificação": "classificacao_db",
    "Banca": "banca_db",
    "Toletagem": "toletagem_db",
}
CLASSES_MAP = {
    "TIPO 2": "Tipo 2",
    "TIPO 4": "Tipo 4",
    "TIPO 7": "Tipo 7",
    # ... outros tipos
}
__QUEBRA__ = "__QUEBRA__" # Constante para representar quebra

# Mock de logger e app Flask
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class MockApp:
    def route(self, path, methods):
        def decorator(func):
            func.route_info = {'path': path, 'methods': methods}
            return func
        return decorator

class MockRequest:
    def get_json(self, silent=False):
        # Simula um payload JSON
        return {
            "produtor_id": 123,
            "tipo_alho": "São Valentim",
            "local": "banca",
            "local_origem": "Classificação",
            "horas_banca": 2,
            "detalhes": [
                {"classe": "TIPO 2",     "peso": 500, "tipo": "classe"},
                {"classe": "TIPO 4",     "peso": 300, "tipo": "classe"},
                {"classe": "INDÚSTRIA",  "peso":  80, "tipo": "industria"},
                {"classe": "__QUEBRA__", "peso":   2, "tipo": "quebra"}
            ]
        }

class MockSession:
    def get(self, key):
        # Simula a sessão do usuário
        return 'banca' # Exemplo de role

class MockResponse:
    def __init__(self, data, status_code):
        self.data = data
        self.status_code = status_code

    def get_json(self):
        return self.data

def jsonify(data, status_code=200):
    return MockResponse(data, status_code)

app = MockApp()
request = MockRequest()
session = MockSession()
# --- Fim do Mock ---


# ─────────────────────────────────────────────────────────────────────────────
#  registrar_movimentacao (substitui a versão anterior)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_movimentacao(produtor_id: int, tipo_alho: str, classe: str, peso: float,
                            local_destino: str, horas_banca: float = 0.0,
                            peso_quebra_origem: float = 0.0, local_origem: str = None) -> tuple[bool, any]:
    """
    Registra UMA entrada/movimentação de estoque para uma classe específica.

    Esta função gerencia a retirada de itens do estoque de origem (se especificado)
    e a inserção no estoque de destino. Inclui validação de saldo e tratamento
    de perdas (quebra).

    Parâmetros
    ----------
    produtor_id : int
        Identificador único do produtor.
    tipo_alho : str
        Tipo específico do alho (ex: "São Valentim").
    classe : str
        Classe do alho a ser movimentado (ex: "Tipo 2", "Indústria").
    peso : float
        Peso em kg que VAI ENTRAR no destino.
    local_destino : str
        Nome do local de destino do estoque (ex: "banca").
    horas_banca : float, optional
        Horas de processamento na banca, se aplicável. Padrão é 0.0.
    peso_quebra_origem : float, optional
        Peso em kg que SAEM da origem como perda (não vão ao destino).
        Só faz sentido quando a `classe` é __QUEBRA__ ou quando se quer
        registrar perda junto com a movimentação. Padrão é 0.0.
    local_origem : str, optional
        Se informado, retira (peso + peso_quebra_origem) da origem.
        Padrão é None.

    Retorna
    -------
    tuple[bool, any]
        Um booleano indicando sucesso (True) ou falha (False), e uma mensagem
        ou o ID da entrada criada em caso de sucesso.
    """
    # Utiliza um gerenciador de contexto para garantir que a conexão seja fechada
    # e as transações sejam tratadas corretamente.
    conn = None
    try:
        conn = conectar_banco()
        if not conn:
            # Retorna erro se a conexão falhar.
            return False, "Erro de conexão com o banco de dados."

        # Inicia a transação implicitamente ao obter o cursor.
        cursor = conn.cursor()
        local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)

        # --- Tratamento da Retirada da Origem (se aplicável) ---
        if local_origem:
            local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
            total_retirar_da_origem = peso + peso_quebra_origem

            # Validação de saldo na origem antes de qualquer operação.
            # Usa COALESCE para tratar casos onde não há registros, retornando 0.
            cursor.execute("""
                SELECT COALESCE(SUM(peso), 0)
                FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                  AND local_estoque = %s AND peso > 0
            """, (produtor_id, tipo_alho, classe, local_origem_banco))
            saldo_origem = float(cursor.fetchone()[0])

            # Verifica se o saldo é suficiente, permitindo uma pequena margem de erro (0.001).
            if saldo_origem < total_retirar_da_origem - 0.001:
                # Fecha cursor e conexão antes de retornar o erro.
                cursor.close()
                conn.close()
                return False, (
                    f"Saldo insuficiente em '{local_origem_banco}' para a classe '{classe}'. "
                    f"Disponível: {saldo_origem:.3f} kg, necessário: {total_retirar_da_origem:.3f} kg"
                )

            # Retira o peso do estoque de origem utilizando a lógica FIFO (First-In, First-Out).
            cursor.execute("""
                SELECT id, peso FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                  AND local_estoque = %s AND peso > 0
                ORDER BY data_registro ASC -- Garante a ordem FIFO
            """, (produtor_id, tipo_alho, classe, local_origem_banco))

            restante_a_retirar = total_retirar_da_origem
            for eid, epeso_float in cursor.fetchall():
                epeso = float(epeso_float) # Converte para float para garantir precisão
                if restante_a_retirar <= 0.001:
                    break # Já retiramos o necessário

                # Calcula quanto retirar deste item específico
                retirar_deste_item = min(restante_a_retirar, epeso)

                if abs(retirar_deste_item - epeso) < 0.001: # Se vamos retirar tudo ou quase tudo
                    cursor.execute("DELETE FROM estoque WHERE id = %s", (eid,))
                else: # Se vamos retirar apenas uma parte
                    novo_peso = round(epeso - retirar_deste_item, 4)
                    cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s",
                                   (novo_peso, eid))
                restante_a_retirar -= retirar_deste_item

            # Registra a perda (quebra) se houver peso especificado para isso.
            if peso_quebra_origem > 0.001:
                cursor.execute("""
                    INSERT INTO perdas
                        (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (produtor_id, tipo_alho, classe,
                      round(peso_quebra_origem, 4),
                      local_origem_banco,
                      "Quebra/Sujeira na movimentação"))

        # --- Inserção no Estoque de Destino ---
        entrada_id = None
        # Insere no destino apenas se houver peso a ser adicionado.
        if peso > 0.001:
            cursor.execute("""
                INSERT INTO estoque
                    (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id -- Retorna o ID da nova entrada
            """, (produtor_id, tipo_alho, classe, round(peso, 4),
                  local_destino_banco, horas_banca))
            # Captura o ID retornado pela instrução SQL.
            result = cursor.fetchone()
            if result:
                entrada_id = result[0]

        # Confirma a transação se todas as operações foram bem-sucedidas.
        conn.commit()
        cursor.close()
        conn.close()
        # Retorna sucesso e o ID da entrada (ou None se nenhum peso foi inserido).
        return True, entrada_id

    except Exception as e:
        # Em caso de qualquer erro, desfaz todas as alterações da transação.
        logger.error(f"Erro ao registrar movimentação para produtor {produtor_id}, tipo {tipo_alho}, classe '{classe}': {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        # Retorna falha com a mensagem de erro.
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
#  registrar_apenas_quebra_na_origem
#  Usada para o item tipo='quebra' que NÃO tem classe específica —
#  retira o peso proporcionalmente de todas as classes da origem.
# ─────────────────────────────────────────────────────────────────────────────

def registrar_apenas_quebra_na_origem(produtor_id: int, tipo_alho: str, peso_quebra: float,
                                       local_origem: str) -> tuple[bool, any]:
    """
    Remove `peso_quebra` kg do estoque de origem distribuindo a retirada
    proporcionalmente entre as classes disponíveis (usando FIFO global)
    e registra o total como perda.

    Esta função é específica para registrar perdas que não estão associadas
    a uma classe de produto específica no destino, mas sim a uma perda geral
    do lote na origem.

    Parâmetros
    ----------
    produtor_id : int
        Identificador único do produtor.
    tipo_alho : str
        Tipo específico do alho (ex: "São Valentim").
    peso_quebra : float
        Peso total em kg a ser registrado como perda.
    local_origem : str
        Nome do local de onde o peso será retirado (ex: "Classificação").

    Retorna
    -------
    tuple[bool, any]
        Um booleano indicando sucesso (True) ou falha (False), e uma mensagem
        em caso de falha.
    """
    conn = None
    try:
        conn = conectar_banco()
        if not conn:
            return False, "Erro de conexão com o banco de dados."

        cursor = conn.cursor()
        local_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)

        # Verifica o saldo total disponível na origem para garantir que a quebra possa ser coberta.
        cursor.execute("""
            SELECT COALESCE(SUM(peso), 0) FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND local_estoque = %s AND peso > 0
        """, (produtor_id, tipo_alho, local_banco))
        saldo_total_origem = float(cursor.fetchone()[0])

        # Valida se o saldo total é suficiente para cobrir o peso da quebra.
        if saldo_total_origem < peso_quebra - 0.001:
            cursor.close()
            conn.close()
            return False, (
                f"Saldo total insuficiente em '{local_banco}' para registrar quebra. "
                f"Disponível: {saldo_total_origem:.3f} kg, quebra: {peso_quebra:.3f} kg"
            )

        # Seleciona todos os itens de estoque elegíveis para retirada, ordenados por data_registro (FIFO global).
        cursor.execute("""
            SELECT id, classe, peso FROM estoque
            WHERE produtor_id = %s AND tipo_alho = %s AND local_estoque = %s AND peso > 0
            ORDER BY data_registro ASC -- FIFO global
        """, (produtor_id, tipo_alho, local_banco))
        entradas_estoque = cursor.fetchall()

        restante_a_retirar = peso_quebra
        # Dicionário para acumular o peso da quebra por classe, para registro detalhado na tabela 'perdas'.
        perdas_detalhadas_por_classe = {}

        # Itera sobre os itens de estoque para retirar o peso da quebra.
        for eid, classe, epeso_float in entradas_estoque:
            epeso = float(epeso_float)
            if restante_a_retirar <= 0.001:
                break # Já retiramos o peso total necessário.

            # Calcula quanto retirar deste item específico.
            retirar_deste_item = min(restante_a_retirar, epeso)

            # Acumula o peso retirado para esta classe.
            perdas_detalhadas_por_classe[classe] = perdas_detalhadas_por_classe.get(classe, 0) + retirar_deste_item

            # Atualiza ou deleta o item de estoque conforme o peso retirado.
            if abs(retirar_deste_item - epeso) < 0.001: # Se vamos retirar tudo ou quase tudo
                cursor.execute("DELETE FROM estoque WHERE id = %s", (eid,))
            else: # Se vamos retirar apenas uma parte
                novo_peso = round(epeso - retirar_deste_item, 4)
                cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s",
                               (novo_peso, eid))
            restante_a_retirar -= retirar_deste_item

        # Insere os registros de perda na tabela 'perdas', detalhados por classe.
        for classe, peso_perdido in perdas_detalhadas_por_classe.items():
            cursor.execute("""
                INSERT INTO perdas
                    (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (produtor_id, tipo_alho, classe, round(peso_perdido, 4),
                  local_banco, "Quebra/Sujeira na movimentação"))

        # Confirma a transação.
        conn.commit()
        cursor.close()
        conn.close()
        # Retorna sucesso. O segundo elemento é None pois não há um ID de entrada a retornar.
        return True, None

    except Exception as e:
        # Em caso de erro, desfaz a transação e loga o erro.
        logger.error(f"Erro ao registrar quebra na origem para produtor {produtor_id}, tipo {tipo_alho}: {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        # Retorna falha com a mensagem de erro.
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
#  api_salvar_entrada  (substitui a versão anterior)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    """
    Endpoint da API para registrar a entrada de alho no sistema,
    gerenciando movimentações entre locais e registrando perdas.

    Payload esperado:
    {
        "produtor_id":  123,
        "tipo_alho":    "São Valentim",
        "local":        "banca",         // Local de DESTINO
        "local_origem": "Classificação", // Local de ORIGEM (opcional, dependendo do role)
        "horas_banca":  2,               // Horas de processamento na banca
        "detalhes": [
            {"classe": "TIPO 2",     "peso": 500, "tipo": "classe"},
            {"classe": "TIPO 4",     "peso": 300, "tipo": "classe"},
            {"classe": "INDÚSTRIA",  "peso":  80, "tipo": "industria"},
            {"classe": "__QUEBRA__", "peso":   2, "tipo": "quebra"}
        ]
    }

    Tipos de item em `detalhes`:
      "classe"    → vai para o estoque do DESTINO como classe TIPO X
      "industria" → vai para o estoque do DESTINO como classe Indústria
      "quebra"    → é PERDA: sai da ORIGEM e vai para `perdas`
                    NÃO entra em nenhum destino
    """
    # Obtém os dados JSON do request. silent=True evita exceção se o JSON for inválido.
    data = request.get_json(silent=True)
    if not data:
        # Retorna erro 400 se os dados JSON forem inválidos ou ausentes.
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos ou formato incorreto.'}), 400

    # Verifica a permissão do usuário com base na sessão.
    role = session.get('tipo')
    # Lista de roles permitidos para esta operação.
    roles_permitidos = ('classificacao', 'banca', 'toletagem', 'superadmin')
    if role not in roles_permitidos:
        # Retorna erro 403 se o usuário não tiver permissão.
        return jsonify({'sucesso': False, 'mensagem': 'Acesso não autorizado.'}), 403

    # Extrai os dados do payload, com valores padrão para campos opcionais.
    produtor_id   = data.get('produtor_id')
    tipo_alho     = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem  = data.get('local_origem')
    detalhes      = data.get('detalhes', [])
    # Converte horas_banca para float, tratando None ou string vazia.
    horas_banca   = float(data.get('horas_banca', 0) or 0)

    # --- Validações básicas obrigatórias ---
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado.'})
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado.'})
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum detalhe de peso registrado.'})

    # --- Validações específicas por role do usuário ---
    if role == 'classificacao':
        # O setor de Classificação só pode registrar a entrada inicial no seu próprio local.
        if local_destino != 'Classificação':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Classificação só pode registrar entrada inicial em "Classificação".'})
        # Classificação não deve ter origem definida e não pode registrar horas de banca.
        local_origem = None
        if horas_banca > 0:
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Classificação não permite registro de horas de banca.'})

    elif role == 'banca':
        # O setor de Banca só pode transferir para o local "banca".
        if local_destino != 'banca':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Banca só pode registrar movimentação para "banca".'})
        # A origem para Banca deve ser Classificação ou Toletagem.
        if not local_origem or local_origem not in ('Classificação', 'Toletagem'):
            return jsonify({'sucesso': False,
                            'mensagem': 'Para o setor Banca, a origem deve ser "Classificação" ou "Toletagem".'})

    elif role == 'toletagem':
        # O setor de Toletagem só pode transferir para o local "toletagem".
        if local_destino != 'toletagem':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Toletagem só pode registrar movimentação para "toletagem".'})
        # A origem para Toletagem deve ser Classificação ou Banca.
        if not local_origem or local_origem not in ('Classificação', 'Banca'):
            return jsonify({'sucesso': False,
                            'mensagem': 'Para o setor Toletagem, a origem deve ser "Classificação" ou "Banca".'})

    # --- Processamento dos detalhes ---
    # Separa os itens em classes/indústria e quebras para processamento distinto.
    itens_para_estoque = [d for d in detalhes if d.get('tipo') in ('classe', 'industria')]
    itens_quebra       = [d for d in detalhes if d.get('tipo') == 'quebra']

    # Calcula o peso total de quebra a ser processado.
    peso_quebra_total = sum(float(d.get('peso', 0)) for d in itens_quebra)

    # Listas para armazenar os resultados e erros de cada item processado.
    resultados_sucesso = []
    erros_processamento = []
    total_entrou_destino = 0.0
    total_saiu_origem    = 0.0

    # --- Processa itens que vão para o estoque de destino (classes e indústria) ---
    for item in itens_para_estoque:
        classe_ui = item.get('classe')
        peso_item = float(item.get('peso', 0) or 0)

        # Ignora itens com peso zero ou negativo.
        if peso_item <= 0:
            continue

        # Mapeia a classe da interface do usuário para o nome usado no banco de dados.
        if classe_ui == 'INDÚSTRIA':
            classe_banco = 'Indústria'
        else:
            # Utiliza o mapeamento de classes, retornando None se a classe não for encontrada.
            classe_banco = CLASSES_MAP.get(classe_ui)

        # Se a classe não for reconhecida, registra um erro e continua.
        if not classe_banco:
            erros_processamento.append({'classe': classe_ui, 'peso': peso_item, 'erro': f'Classe "{classe_ui}" não reconhecida pelo sistema.'})
            continue

        # Chama a função para registrar a movimentação no banco de dados.
        # O peso_quebra_origem é 0 aqui, pois a quebra é tratada separadamente.
        sucesso, resultado = registrar_movimentacao(
            produtor_id       = produtor_id,
            tipo_alho         = tipo_alho,
            classe            = classe_banco,
            peso              = peso_item,
            local_destino     = local_destino,
            horas_banca       = horas_banca,
            peso_quebra_origem= 0,
            local_origem      = local_origem,
        )

        if sucesso:
            # Armazena o resultado bem-sucedido, incluindo o ID da entrada gerada.
            resultados_sucesso.append({'classe': classe_ui, 'peso': peso_item, 'entrada_id': resultado})
            total_entrou_destino += peso_item
            total_saiu_origem    += peso_item # Peso que saiu da origem para o destino
        else:
            # Armazena o erro ocorrido.
            erros_processamento.append({'classe': classe_ui, 'peso': peso_item, 'erro': resultado})

    # --- Processa itens de quebra / sujeira ---
    # A quebra é retirada da ORIGEM (proporcionalmente entre as classes disponíveis)
    # e registrada como perda. Não entra em nenhum destino.
    # Só processa se houver peso de quebra e se uma origem foi especificada.
    if peso_quebra_total > 0.001 and local_origem:
        sucesso, msg = registrar_apenas_quebra_na_origem(
            produtor_id  = produtor_id,
            tipo_alho    = tipo_alho,
            peso_quebra  = peso_quebra_total,
            local_origem = local_origem,
        )
        if sucesso:
            # Registra a quebra como um item de sucesso, sem entrada_id.
            resultados_sucesso.append({'classe': 'Quebra/Sujeira', 'peso': peso_quebra_total,
                                       'entrada_id': None, 'tipo': 'perda'})
            total_saiu_origem += peso_quebra_total # Peso que saiu da origem como perda
        else:
            # Armazena o erro ocorrido no processamento da quebra.
            erros_processamento.append({'classe': 'Quebra/Sujeira', 'peso': peso_quebra_total, 'erro': msg})

    # --- Montagem da Resposta Final ---

    # Se houve erros e nenhum sucesso, retorna um erro 400 com o primeiro erro encontrado.
    if erros_processamento and not resultados_sucesso:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro crítico: {erros_processamento[0]["erro"]}',
            'erros': erros_processamento,
        }), 400

    # Se houve erros misturados com sucessos, retorna um código 207 (Multi-Status).
    if erros_processamento:
        return jsonify({
            'sucesso': False, # Indica que nem tudo foi bem-sucedido
            'mensagem': f'Alguns itens falharam no processamento. Verifique os detalhes. Primeiro erro: {erros_processamento[0]["erro"]}',
            'sucessos': resultados_sucesso,
            'erros':    erros_processamento,
        }), 207 # Código 207 Multi-Status

    # Se tudo ocorreu com sucesso.
    msg_sucesso = f'Registrado com sucesso! Total entrado no destino: {total_entrou_destino:.2f} kg.'
    if peso_quebra_total > 0.001:
        msg_sucesso += f' | Quebra/Sujeira removida da origem: {peso_quebra_total:.2f} kg.'
    if horas_banca > 0:
        msg_sucesso += f' | Horas de banca: {horas_banca}.'
    if local_origem:
        msg_sucesso += f' | Origem: {local_origem}.'

    # Retorna sucesso 200 com a mensagem e os registros criados.
    return jsonify({'sucesso': True, 'mensagem': msg_sucesso, 'registros': resultados_sucesso})
