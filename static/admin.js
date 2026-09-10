// ═══════════════════════════════════════════════════════════════════════
// MODAL DE DESCONTO + LIMPAR BANCO
// Cole este bloco no final do gerente.html, antes do </script>
// ═══════════════════════════════════════════════════════════════════════

let descontoEditando = null;

window.abrirModalDesconto = function(id = null) {
    descontoEditando = id;
    const modal = document.createElement('div');
    modal.id = 'modalDesconto';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000;display:flex;align-items:center;justify-content:center;padding:1rem';
    
    let dados = {nome:'', tipo:'percentual', valor:'', ativo:true, ordem:0};
    if (id) {
        // Buscar dados
        fetch('/api/descontos/listar').then(r=>r.json()).then(lista => {
            const d = lista.find(x => x.id === id);
            if (d) {
                document.getElementById('descNome').value = d.nome;
                document.getElementById('descTipo').value = d.tipo;
                document.getElementById('descValor').value = d.valor;
                document.getElementById('descAtivo').checked = d.ativo;
                document.getElementById('descOrdem').value = d.ordem;
            }
        });
    }
    
    modal.innerHTML = `
        <div style="background:#fff;border-radius:12px;max-width:480px;width:100%;padding:1.5rem">
            <h3 style="margin-bottom:1rem;color:#0a3d2c;font-size:1.1rem">
                ${id ? 'Editar Desconto' : 'Novo Desconto'}
            </h3>
            <div style="display:flex;flex-direction:column;gap:.75rem">
                <div>
                    <label style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#6b7280;display:block;margin-bottom:.3rem">Nome</label>
                    <input id="descNome" type="text" style="width:100%;padding:.6rem;border:1.5px solid #d1d5db;border-radius:6px" placeholder="Ex: Comissão COPAR">
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem">
                    <div>
                        <label style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#6b7280;display:block;margin-bottom:.3rem">Tipo</label>
                        <select id="descTipo" style="width:100%;padding:.6rem;border:1.5px solid #d1d5db;border-radius:6px">
                            <option value="percentual">Percentual (%)</option>
                            <option value="valor">Valor Fixo (R$)</option>
                        </select>
                    </div>
                    <div>
                        <label style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#6b7280;display:block;margin-bottom:.3rem">Valor</label>
                        <input id="descValor" type="number" step="0.01" style="width:100%;padding:.6rem;border:1.5px solid #d1d5db;border-radius:6px" placeholder="0.00">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem">
                    <div>
                        <label style="font-size:.7rem;font-weight:700;text-transform:uppercase;color:#6b7280;display:block;margin-bottom:.3rem">Ordem</label>
                        <input id="descOrdem" type="number" value="0" style="width:100%;padding:.6rem;border:1.5px solid #d1d5db;border-radius:6px">
                    </div>
                    <div style="display:flex;align-items:flex-end;padding-bottom:.6rem">
                        <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.85rem">
                            <input id="descAtivo" type="checkbox" checked> Ativo
                        </label>
                    </div>
                </div>
            </div>
            <div style="display:flex;gap:.5rem;margin-top:1.25rem">
                <button onclick="fecharModalDesconto()" style="flex:1;padding:.7rem;border:1.5px solid #d1d5db;background:#fff;border-radius:6px;cursor:pointer;font-weight:600">Cancelar</button>
                <button onclick="salvarDesconto()" style="flex:1;padding:.7rem;background:#0a3d2c;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600">Salvar</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
};

window.fecharModalDesconto = function() {
    document.getElementById('modalDesconto')?.remove();
};

window.salvarDesconto = async function() {
    const dados = {
        id: descontoEditando,
        nome: document.getElementById('descNome').value,
        tipo: document.getElementById('descTipo').value,
        valor: parseFloat(document.getElementById('descValor').value),
        ativo: document.getElementById('descAtivo').checked,
        ordem: parseInt(document.getElementById('descOrdem').value) || 0
    };
    if (!dados.nome || !dados.valor) {
        alert('Preencha nome e valor');
        return;
    }
    const r = await fetch('/api/descontos/salvar', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(dados)
    });
    const res = await r.json();
    if (res.sucesso) {
        fecharModalDesconto();
        carregarDescontos();
    } else {
        alert('Erro: ' + res.mensagem);
    }
};

window.editarDesconto = function(id) { abrirModalDesconto(id); };

window.excluirDesconto = async function(id) {
    if (!confirm('Excluir este desconto?')) return;
    const r = await fetch('/api/descontos/excluir', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({id})
    });
    const d = await r.json();
    if (d.sucesso) carregarDescontos();
};

// ═══════════════════════════════════════════════════════════════════════
// PAINEL DE ADMINISTRAÇÃO (LIMPAR BANCO)
// ═══════════════════════════════════════════════════════════════════════

async function carregarAdministracao(container) {
    container.innerHTML = `
        <div class="secao">
            <div class="secao-header" style="background:#991b1b">
                <span>⚠️ Administração — Zona de Perigo</span>
            </div>
            <div style="padding:1.5rem">
                <div style="background:#fee2e2;border-left:4px solid #991b1b;padding:1rem;border-radius:6px;margin-bottom:1.5rem">
                    <h3 style="color:#991b1b;margin-bottom:.5rem;font-size:1rem">Atenção: Ação Irreversível</h3>
                    <p style="font-size:.85rem;color:#7f1d1d;line-height:1.6">
                        Esta ação irá <strong>remover permanentemente</strong> todos os registros de:
                    </p>
                    <ul style="margin:.75rem 0 0 1.5rem;font-size:.85rem;color:#7f1d1d;line-height:1.8">
                        <li>Vendas (histórico completo)</li>
                        <li>Pagamentos (todos os recibos)</li>
                        <li>Estoque (todas as movimentações)</li>
                        <li>Créditos dos produtores</li>
                    </ul>
                    <p style="font-size:.85rem;color:#7f1d1d;margin-top:.75rem">
                        <strong>Preservado:</strong> cadastro dos produtores (nome, CPF, matrícula) e configurações.
                    </p>
                </div>
                
                <button onclick="confirmarLimpeza()" style="
                    background:#991b1b;color:#fff;border:none;padding:1rem 2rem;
                    border-radius:8px;font-weight:700;font-size:1rem;cursor:pointer;
                    width:100%;max-width:400px">
                    🗑️ Limpar Todos os Dados Transacionais
                </button>
                
                <div style="margin-top:2rem;padding-top:1.5rem;border-top:1px solid #e5e7eb">
                    <h3 style="font-size:.9rem;margin-bottom:.75rem;color:#374151">Estatísticas Atuais</h3>
                    <div id="statsBanco" style="font-size:.85rem;color:#6b7280">
                        Carregando...
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Carrega estatísticas atuais
    const stats = await api('/api/gerente/estatisticas');
    if (stats) {
        document.getElementById('statsBanco').innerHTML = `
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem">
                <div style="background:#f9fafb;padding:.75rem 1rem;border-radius:6px">
                    <div style="font-size:.7rem;text-transform:uppercase;color:#6b7280;font-weight:700">Produtores</div>
                    <div style="font-size:1.2rem;font-weight:700;color:#0a3d2c">${stats.total_produtores || 0}</div>
                </div>
                <div style="background:#f9fafb;padding:.75rem 1rem;border-radius:6px">
                    <div style="font-size:.7rem;text-transform:uppercase;color:#6b7280;font-weight:700">Estoque Total</div>
                    <div style="font-size:1.2rem;font-weight:700;color:#0a3d2c">${(stats.total_estoque_kg || 0).toLocaleString('pt-BR')} kg</div>
                </div>
                <div style="background:#f9fafb;padding:.75rem 1rem;border-radius:6px">
                    <div style="font-size:.7rem;text-transform:uppercase;color:#6b7280;font-weight:700">Vendas no Mês</div>
                    <div style="font-size:1.2rem;font-weight:700;color:#0a3d2c">R$ ${(stats.vendas_mes || 0).toFixed(2)}</div>
                </div>
                <div style="background:#f9fafb;padding:.75rem 1rem;border-radius:6px">
                    <div style="font-size:.7rem;text-transform:uppercase;color:#6b7280;font-weight:700">Pagamentos no Mês</div>
                    <div style="font-size:1.2rem;font-weight:700;color:#0a3d2c">R$ ${(stats.pagamentos_mes || 0).toFixed(2)}</div>
                </div>
            </div>
        `;
    }
}

window.confirmarLimpeza = function() {
    const modal = document.createElement('div');
    modal.id = 'modalLimpeza';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;display:flex;align-items:center;justify-content:center;padding:1rem';
    modal.innerHTML = `
        <div style="background:#fff;border-radius:12px;max-width:500px;width:100%;padding:1.5rem">
            <h3 style="color:#991b1b;margin-bottom:1rem">⚠️ Confirmação de Segurança</h3>
            <p style="font-size:.88rem;color:#374151;margin-bottom:1rem;line-height:1.6">
                Para confirmar a limpeza, digite a frase exata abaixo:
            </p>
            <div style="background:#f3f4f6;padding:.75rem;border-radius:6px;margin-bottom:1rem;font-family:monospace;font-size:.85rem;text-align:center;letter-spacing:.05em">
                CONFIRMAR LIMPEZA
            </div>
            <input type="text" id="confirmacaoInput" style="
                width:100%;padding:.75rem;border:1.5px solid #d1d5db;border-radius:6px;
                font-family:monospace;text-transform:uppercase" placeholder="Digite a frase">
            <div style="display:flex;gap:.5rem;margin-top:1rem">
                <button onclick="document.getElementById('modalLimpeza').remove()" style="
                    flex:1;padding:.75rem;border:1.5px solid #d1d5db;background:#fff;
                    border-radius:6px;cursor:pointer;font-weight:600">Cancelar</button>
                <button onclick="executarLimpeza()" style="
                    flex:1;padding:.75rem;background:#991b1b;color:#fff;border:none;
                    border-radius:6px;cursor:pointer;font-weight:600">Confirmar Limpeza</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
};

window.executarLimpeza = async function() {
    const conf = document.getElementById('confirmacaoInput').value.trim().toUpperCase();
    if (conf !== 'CONFIRMAR LIMPEZA') {
        alert('Frase de confirmação incorreta');
        return;
    }
    
    const r = await fetch('/api/admin/limpar-banco', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({confirmacao: conf})
    });
    const d = await r.json();
    document.getElementById('modalLimpeza').remove();
    
    if (d.sucesso) {
        alert('✅ ' + d.mensagem + '\n\n' +
              'Vendas removidas: ' + (d.detalhes?.vendas_removidas || 0) + '\n' +
              'Pagamentos removidos: ' + (d.detalhes?.pagamentos_removidos || 0) + '\n' +
              'Registros de estoque removidos: ' + (d.detalhes?.registros_estoque_removidos || 0));
        carregarAdministracao(document.getElementById('conteudo'));
    } else {
        alert('❌ Erro: ' + d.mensagem);
    }
};
