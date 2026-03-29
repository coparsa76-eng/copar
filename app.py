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

# ─────────────────────────────────────────────────────────────────────────────
#  registrar_movimentacao  (substitui a versão anterior)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_movimentacao(produtor_id, tipo_alho, classe, peso,
                            local_destino, horas_banca=0,
                            peso_quebra_origem=0, local_origem=None):
    """
    Registra UMA entrada/movimentação de estoque para uma classe específica.

    Parâmetros
    ----------
    peso               : kg que VAI ENTRAR no destino.
    peso_quebra_origem : kg que SAEM da origem como perda (não vão ao destino).
                         Só faz sentido quando a `classe` é __QUEBRA__ ou quando
                         se quer registrar perda junto com a movimentação.
    local_origem       : se informado, retira (peso + peso_quebra_origem) da origem.
    """
    conn = conectar_banco()
    if not conn:
        return False, "Erro de conexão"
    try:
        cursor = conn.cursor()
        local_destino_banco = MAPEAMENTO_LOCAL.get(local_destino, local_destino)

        if local_origem:
            local_origem_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)
            total_retirar = peso + peso_quebra_origem

            # Verificar saldo
            cursor.execute("""
                SELECT COALESCE(SUM(peso), 0)
                FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                  AND local_estoque = %s AND peso > 0
            """, (produtor_id, tipo_alho, classe, local_origem_banco))
            saldo = float(cursor.fetchone()[0])

            if saldo < total_retirar - 0.001:
                cursor.close(); conn.close()
                return False, (
                    f"Saldo insuficiente em {local_origem_banco} para {classe}. "
                    f"Disponível: {saldo:.3f} kg, necessário: {total_retirar:.3f} kg"
                )

            # Retirar FIFO
            cursor.execute("""
                SELECT id, peso FROM estoque
                WHERE produtor_id = %s AND tipo_alho = %s AND classe = %s
                  AND local_estoque = %s AND peso > 0
                ORDER BY data_registro
            """, (produtor_id, tipo_alho, classe, local_origem_banco))

            restante = total_retirar
            for eid, epeso in cursor.fetchall():
                if restante <= 0.001:
                    break
                epeso = float(epeso)
                if restante >= epeso - 0.001:
                    cursor.execute("DELETE FROM estoque WHERE id = %s", (eid,))
                    restante -= epeso
                else:
                    cursor.execute("UPDATE estoque SET peso = %s WHERE id = %s",
                                   (round(epeso - restante, 4), eid))
                    restante = 0

            # Registrar perda se houver quebra
            if peso_quebra_origem > 0.001:
                cursor.execute("""
                    INSERT INTO perdas
                        (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (produtor_id, tipo_alho, classe,
                      round(peso_quebra_origem, 4),
                      local_origem_banco,
                      "Quebra/Sujeira na movimentação"))

        # Inserir no destino (só se houver peso a inserir)
        entrada_id = None
        if peso > 0.001:
            cursor.execute("""
                INSERT INTO estoque
                    (produtor_id, tipo_alho, classe, peso, local_estoque, horas_banca)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (produtor_id, tipo_alho, classe, round(peso, 4),
                  local_destino_banco, horas_banca))
            entrada_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()
        return True, entrada_id

    except Exception as e:
        logger.error(f"Erro ao registrar movimentação [{classe}]: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
#  registrar_apenas_quebra_na_origem
#  Usada para o item tipo='quebra' que NÃO tem classe específica —
#  retira o peso proporcionalmente de todas as classes da origem.
# ─────────────────────────────────────────────────────────────────────────────

def registrar_apenas_quebra_na_origem(produtor_id, tipo_alho, peso_quebra,
                                       local_origem):
    """
    Remove `peso_quebra` kg do estoque de origem distribuindo entre as classes
    disponíveis (FIFO global) e registra como perda.
    """
    conn = conectar_banco()
    if not conn:
        return False, "Erro de conexão"
    try:
        cursor = conn.cursor()
        local_banco = MAPEAMENTO_LOCAL.get(local_origem, local_origem)

        # Verificar saldo total
        cursor.execute("""
            SELECT COALESCE(SUM(peso), 0) FROM estoque
            WHERE produtor_id=%s AND tipo_alho=%s AND local_estoque=%s AND peso>0
        """, (produtor_id, tipo_alho, local_banco))
        saldo_total = float(cursor.fetchone()[0])

        if saldo_total < peso_quebra - 0.001:
            cursor.close(); conn.close()
            return False, (
                f"Saldo insuficiente em {local_banco} para registrar quebra. "
                f"Disponível: {saldo_total:.3f} kg, quebra: {peso_quebra:.3f} kg"
            )

        # FIFO global (sem filtrar classe)
        cursor.execute("""
            SELECT id, classe, peso FROM estoque
            WHERE produtor_id=%s AND tipo_alho=%s AND local_estoque=%s AND peso>0
            ORDER BY data_registro
        """, (produtor_id, tipo_alho, local_banco))
        entradas = cursor.fetchall()

        restante = peso_quebra
        perdas_por_classe = {}   # para registrar detalhado

        for eid, classe, epeso in entradas:
            if restante <= 0.001:
                break
            epeso = float(epeso)
            retirar = min(restante, epeso)
            perdas_por_classe[classe] = perdas_por_classe.get(classe, 0) + retirar

            if retirar >= epeso - 0.001:
                cursor.execute("DELETE FROM estoque WHERE id=%s", (eid,))
            else:
                cursor.execute("UPDATE estoque SET peso=%s WHERE id=%s",
                               (round(epeso - retirar, 4), eid))
            restante -= retirar

        # Inserir perdas por classe
        for classe, peso_p in perdas_por_classe.items():
            cursor.execute("""
                INSERT INTO perdas
                    (produtor_id, tipo_alho, classe, peso_kg, local_origem, motivo)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (produtor_id, tipo_alho, classe, round(peso_p, 4),
                  local_banco, "Quebra/Sujeira na movimentação"))

        conn.commit()
        cursor.close()
        conn.close()
        return True, None

    except Exception as e:
        logger.error(f"Erro ao registrar quebra na origem: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
#  api_salvar_entrada  (substitui a versão anterior)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/salvar-entrada', methods=['POST'])
def api_salvar_entrada():
    """
    Payload do frontend:
    {
        "produtor_id":  123,
        "tipo_alho":    "São Valentim",
        "local":        "banca",
        "local_origem": "Classificação",
        "horas_banca":  2,
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
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'sucesso': False, 'mensagem': 'Dados inválidos'}), 400

    role = session.get('tipo')
    if role not in ('classificacao', 'banca', 'toletagem', 'superadmin'):
        return jsonify({'sucesso': False, 'mensagem': 'Acesso não autorizado'}), 403

    produtor_id   = data.get('produtor_id')
    tipo_alho     = data.get('tipo_alho')
    local_destino = data.get('local')
    local_origem  = data.get('local_origem')
    detalhes      = data.get('detalhes', [])
    horas_banca   = float(data.get('horas_banca', 0) or 0)

    # ── Validações básicas ────────────────────────────
    if not produtor_id:
        return jsonify({'sucesso': False, 'mensagem': 'Produtor não selecionado'})
    if not tipo_alho:
        return jsonify({'sucesso': False, 'mensagem': 'Tipo de alho não selecionado'})
    if not detalhes:
        return jsonify({'sucesso': False, 'mensagem': 'Nenhum peso registrado'})

    # ── Validações por role ───────────────────────────
    if role == 'classificacao':
        if local_destino != 'Classificação':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Classificação só registra entrada inicial.'})
        local_origem = None
        if horas_banca > 0:
            return jsonify({'sucesso': False,
                            'mensagem': 'Classificação não permite horas de banca.'})

    elif role == 'banca':
        if local_destino != 'banca':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Banca só transfere para Banca.'})
        if not local_origem or local_origem not in ('Classificação', 'Toletagem'):
            return jsonify({'sucesso': False,
                            'mensagem': 'Para Banca, a origem deve ser Classificação ou Toletagem.'})

    elif role == 'toletagem':
        if local_destino != 'toletagem':
            return jsonify({'sucesso': False,
                            'mensagem': 'Setor Toletagem só transfere para Toletagem.'})
        if not local_origem or local_origem not in ('Classificação', 'Banca'):
            return jsonify({'sucesso': False,
                            'mensagem': 'Para Toletagem, a origem deve ser Classificação ou Banca.'})

    # ── Separar itens por tipo ────────────────────────
    itens_classe   = [d for d in detalhes if d.get('tipo') in ('classe', 'industria')]
    itens_quebra   = [d for d in detalhes if d.get('tipo') == 'quebra']

    peso_quebra_total = sum(float(d.get('peso', 0)) for d in itens_quebra)

    resultados = []
    erros      = []
    total_entrou_destino = 0
    total_saiu_origem    = 0

    # ── Processar classes + indústria ─────────────────
    for item in itens_classe:
        classe_ui = item.get('classe')
        peso      = float(item.get('peso', 0) or 0)
        if peso <= 0:
            continue

        # Mapear para nome do banco
        if classe_ui == 'INDÚSTRIA':
            classe_banco = 'Indústria'
        else:
            classe_banco = CLASSES_MAP.get(classe_ui)

        if not classe_banco:
            erros.append({'classe': classe_ui, 'erro': f'Classe "{classe_ui}" não reconhecida'})
            continue

        sucesso, resultado = registrar_movimentacao(
            produtor_id       = produtor_id,
            tipo_alho         = tipo_alho,
            classe            = classe_banco,
            peso              = peso,
            local_destino     = local_destino,
            horas_banca       = horas_banca,
            peso_quebra_origem= 0,       # quebra é tratada separado
            local_origem      = local_origem,
        )

        if sucesso:
            resultados.append({'classe': classe_ui, 'peso': peso, 'entrada_id': resultado})
            total_entrou_destino += peso
            total_saiu_origem    += peso
        else:
            erros.append({'classe': classe_ui, 'peso': peso, 'erro': resultado})

    # ── Processar quebra / sujeira ────────────────────
    # A quebra é retirada da ORIGEM (proporcionalmente entre as classes disponíveis)
    # e registrada como perda. Não entra em nenhum destino.
    if peso_quebra_total > 0.001 and local_origem:
        sucesso, msg = registrar_apenas_quebra_na_origem(
            produtor_id  = produtor_id,
            tipo_alho    = tipo_alho,
            peso_quebra  = peso_quebra_total,
            local_origem = local_origem,
        )
        if sucesso:
            resultados.append({'classe': 'Quebra/Sujeira', 'peso': peso_quebra_total,
                               'entrada_id': None, 'tipo': 'perda'})
            total_saiu_origem += peso_quebra_total
        else:
            erros.append({'classe': 'Quebra/Sujeira', 'peso': peso_quebra_total, 'erro': msg})

    # ── Resposta ──────────────────────────────────────
    if erros and not resultados:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Erro: {erros[0]["erro"]}',
            'erros': erros,
        }), 400

    if erros:
        return jsonify({
            'sucesso': False,
            'mensagem': f'Alguns itens falharam: {erros[0]["erro"]}',
            'sucessos': resultados,
            'erros':    erros,
        }), 207

    msg = f'Registrado com sucesso! Entrou no destino: {total_entrou_destino:.2f} kg'
    if peso_quebra_total > 0:
        msg += f' | Quebra/Sujeira removida da origem: {peso_quebra_total:.2f} kg'
    if horas_banca > 0:
        msg += f' | Horas: {horas_banca}'
    if local_origem:
        msg += f' | Origem: {local_origem}'

    return jsonify({'sucesso': True, 'mensagem': msg, 'registros': resultados})
