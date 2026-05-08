import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import segno
import io
import re
import hashlib
import random
import requests
from google.oauth2.service_account import Credentials
import gspread
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Barbearia Elite - Agendamento", layout="centered")

# --- OCULTAR ELEMENTOS PADRÃO DO STREAMLIT (MENU, DEPLOY E FOOTER) ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stHeader"] {display: none;} /* Remove o botão Deploy e a barra superior */
    </style>
    """, unsafe_allow_html=True)

# --- INICIALIZA ESTADOS DE SESSÃO ---
if "horarios_bloqueados_sessao" not in st.session_state:
    st.session_state["horarios_bloqueados_sessao"] = []
if "cliente_logado" not in st.session_state:
    st.session_state["cliente_logado"] = None
if "admin_autenticado" not in st.session_state:
    st.session_state["admin_autenticado"] = False
if "recuperar_senha_fluxo" not in st.session_state:
    st.session_state["recuperar_senha_fluxo"] = {"passo": "login", "telefone": "", "codigo": "", "nome_cliente": ""}

# --- CONEXÃO SEGURA COM O GOOGLE SHEETS ---
@st.cache_resource
def conectar_banco():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        raw_key = creds_dict["private_key"]
        cleaned_lines = [line.strip() for line in raw_key.replace("\\n", "\n").split("\n") if line.strip()]
        creds_dict["private_key"] = "\n".join(cleaned_lines)

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        return client.open("Agendamentos Barbearia")
    except Exception as e:
        return None

banco = conectar_banco()
if banco is None:
    st.error("⚠️ Erro ao conectar com o banco de dados. Verifique a API do Drive e o Secrets.")
    st.stop()

# --- INSTANCIA AS ABAS DO BANCO DE DADOS (E AUTO-PROVISIONA SE NECESSÁRIO) ---
planilha_agendamentos = banco.sheet1

# Auto-provisionamento da aba 'Serviços'
try:
    planilha_servicos = banco.worksheet("Serviços")
except Exception:
    planilha_servicos = banco.add_worksheet(title="Serviços", rows="100", cols="2")
    planilha_servicos.append_row(["Serviço", "Preço"])
    planilha_servicos.append_row(["Corte Simples", "30"])
    planilha_servicos.append_row(["Barba", "20"])
    planilha_servicos.append_row(["Combo", "45"])

# Auto-provisionamento da aba 'Clientes'
try:
    planilha_clientes = banco.worksheet("Clientes")
except Exception:
    planilha_clientes = banco.add_worksheet(title="Clientes", rows="1000", cols="5")
    planilha_clientes.append_row(["Nome", "Telefone", "Rede_Social", "Senha_Hash", "Data_Cadastro"])

# Auto-provisionamento da aba 'Configuracoes'
try:
    planilha_configuracoes = banco.worksheet("Configuracoes")
except Exception:
    planilha_configuracoes = banco.add_worksheet(title="Configuracoes", rows="50", cols="2")
    planilha_configuracoes.append_row(["Chave", "Valor"])


# --- FUNÇÕES DE SEGURANÇA E AUTH ---
def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def obter_senha_admin_hash():
    """Lê a senha do Admin salva no Sheets ou usa a do Secrets como fallback inicial"""
    try:
        valores = planilha_configuracoes.get_all_values()
        for linha in valores[1:]:
            if len(linha) >= 2 and linha[0] == "senha_admin_hash":
                return str(linha[1]).strip()
    except Exception:
        pass
    return hash_senha(st.secrets.get("senha_admin", "admin123"))

def atualizar_senha_admin(nova_senha):
    """Atualiza a senha do administrador na aba de configurações"""
    senha_hash = hash_senha(nova_senha)
    try:
        valores = planilha_configuracoes.get_all_values()
        encontrou = False
        for idx_linha, linha in enumerate(valores, start=1):
            if len(linha) >= 2 and linha[0] == "senha_admin_hash":
                planilha_configuracoes.update_cell(idx_linha, 2, senha_hash)
                encontrou = True
                break
        if not encontrou:
            planilha_configuracoes.append_row(["senha_admin_hash", senha_hash])
        return True
    except Exception:
        return False

def cadastrar_novo_cliente(nome, telefone, rede_social, senha):
    try:
        tel_limpo = re.sub(r'\D', '', telefone)
        if len(tel_limpo) < 10:
            return False, "⚠️ Telefone inválido. Digite DDD + Número."
            
        insta_limpo = rede_social.replace("@", "").replace(" ", "").strip().lower()
        valores = planilha_clientes.get_all_values()
        
        if len(valores) > 1:
            for linha in valores[1:]:
                if len(linha) >= 2:
                    tel_banco = re.sub(r'\D', '', str(linha[1]))
                    if tel_banco == tel_limpo:
                        return False, "⚠️ Este WhatsApp já está cadastrado em outra conta. Faça login!"
                
                if len(linha) >= 3 and insta_limpo:
                    insta_banco = str(linha[2]).replace("@", "").replace(" ", "").strip().lower()
                    if insta_banco == insta_limpo:
                        return False, f"⚠️ O Instagram @{insta_limpo} já está vinculado a outro cliente."
        
        senha_cripto = hash_senha(senha)
        registro_now = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
        
        planilha_clientes.append_row([nome, formatar_telefone(tel_limpo), insta_limpo, senha_cripto, registro_now])
        return True, "🎉 Cadastro realizado com sucesso!"
    except Exception as e:
        return False, f"Erro no banco de dados: {e}"

def autenticar_cliente(telefone, senha):
    try:
        tel_limpo = re.sub(r'\D', '', telefone)
        senha_cripto = hash_senha(senha)
        valores = planilha_clientes.get_all_values()
        
        for linha in valores[1:]:
            if len(linha) >= 4:
                tel_banco = re.sub(r'\D', '', str(linha[1]))
                senha_banco = str(linha[3]).strip()
                if tel_banco == tel_limpo and senha_banco == senha_cripto:
                    return {
                        "nome": str(linha[0]),
                        "telefone": str(linha[1]),
                        "rede_social": str(linha[2])
                    }
        return None
    except Exception:
        return None

def atualizar_senha_cliente(telefone, nova_senha):
    """Atualiza a senha do cliente na planilha 'Clientes'"""
    try:
        tel_limpo = re.sub(r'\D', '', telefone)
        senha_cripto = hash_senha(nova_senha)
        valores = planilha_clientes.get_all_values()
        
        for idx, linha in enumerate(valores, start=1):
            if len(linha) >= 2:
                tel_banco = re.sub(r'\D', '', str(linha[1]))
                if tel_banco == tel_limpo:
                    planilha_clientes.update_cell(idx, 4, senha_cripto)
                    return True
        return False
    except Exception:
        return False

def obter_todos_clientes():
    try:
        valores = planilha_clientes.get_all_values()
        if len(valores) <= 1:
            return []
        
        clientes = []
        for linha in valores[1:]:
            if len(linha) >= 5:
                clientes.append({
                    "Nome": str(linha[0]),
                    "Telefone": str(linha[1]),
                    "Rede_Social": str(linha[2]),
                    "Data_Cadastro": str(linha[4])
                })
        return clientes
    except Exception:
        return []


# --- SISTEMA DE ENVIO DO CÓDIGO DE RECUPERAÇÃO ---
def enviar_codigo_recuperacao_whatsapp(nome, telefone, codigo):
    """
    Função pronta para produção. Atualmente gera um toast de notificação flutuante para testes locais,
    mas deixei o código de chamada da API do WhatsApp ou SMS pronto para você plugar seu gateway.
    """
    # Exibe notificação flutuante no canto da tela (perfeito para testar e validar)
    st.toast(f"🔑 [WHATSAPP API] Olá {nome}! Seu código de segurança é: {codigo}", icon="💬")
    
    # --- EXEMPLO REAL DE INTEGRAÇÃO COM SEU GATEWAY DE WHATSAPP (EX: Z-API / EVOLUTION API) ---
    # url = "https://api.z-api.io/instances/SUA_INSTANCIA/token/SEU_TOKEN/send-text"
    # payload = {
    #     "phone": "55" + re.sub(r'\D', '', telefone),
    #     "message": f"Olá {nome}! Seu código de segurança para redefinir sua senha na Barbearia Elite é: {codigo}"
    # }
    # headers = {"Content-Type": "application/json"}
    # try:
    #     requests.post(url, json=payload, headers=headers, timeout=5)
    # except Exception:
    #     pass


# --- FUNÇÕES DE CADASTRO E BUSCA DE SERVIÇOS ---
def obter_servicos():
    try:
        valores = planilha_servicos.get_all_values()
        if len(valores) <= 1:
            return [("Corte Simples", 30), ("Barba", 20), ("Combo", 45)]
        
        lista = []
        for linha in valores[1:]:
            if len(linha) >= 2 and str(linha[0]).strip():
                nome = str(linha[0]).strip()
                try:
                    preco = int(str(linha[1]).strip())
                except ValueError:
                    preco = 0
                lista.append((nome, preco))
        return lista
    except Exception:
        return [("Corte Simples", 30), ("Barba", 20), ("Combo", 45)]


# --- FUNÇÕES DE NORMALIZAÇÃO DE DADOS ---
def normalizar_data(data_str):
    data_str = data_str.replace("'", "").strip()
    for formato in ["%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(data_str, formato)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    return data_str

def normalizar_hora(hora_str):
    hora_str = hora_str.replace("'", "").strip()
    if ":" in hora_str:
        partes = hora_str.split(":")
        if len(partes) >= 2:
            h = partes[0].zfill(2)
            m = partes[1].zfill(2)
            return f"{h}:{m}"
    return hora_str


# --- FUNÇÕES DE LÓGICA E BLINDAGEM ---
def pegar_hora_local():
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)

def formatar_telefone(numero_cru):
    numeros = re.sub(r'\D', '', numero_cru)
    if len(numeros) == 11:
        return f"({numeros[:2]}) {numeros[2]} {numeros[3:7]}-{numeros[7:]}"
    elif len(numeros) == 10:
        return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
    return numero_cru

def obter_horarios_ocupados(data_str):
    try:
        valores = planilha_agendamentos.get_all_values()
        if len(valores) == 0:
            return []
            
        primeira_celula = str(valores[0][0]).strip().lower()
        tem_cabecalho = primeira_celula in ["nome", "cliente", "client"]
        inicio = 1 if tem_cabecalho else 0
            
        ocupados = []
        target_data = normalizar_data(data_str)
        
        for linha in valores[inicio:]:
            if len(linha) > 3:
                p_data = normalizar_data(str(linha[2]))
                p_hora = normalizar_hora(str(linha[3]))
                    
                if p_data == target_data:
                    ocupados.append(p_hora)
        return ocupados
    except Exception as e:
        return []

def gerar_horarios_disponiveis(data_selecionada):
    grade = []
    atual = datetime.strptime("08:00", "%H:%M")
    fim = datetime.strptime("18:30", "%H:%M")
    
    while atual <= fim:
        grade.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=30)
    
    data_str = data_selecionada.strftime("%d/%m/%Y")
    
    ocupados_planilha = obter_horarios_ocupados(data_str)
    ocupados_sessao = [h for d, h in st.session_state["horarios_bloqueados_sessao"] if normalizar_data(d) == normalizar_data(data_str)]
    todos_ocupados = ocupados_planilha + ocupados_sessao
    
    agora = pegar_hora_local()
    if data_selecionada == agora.date():
        hora_atual = agora.strftime("%H:%M")
        grade = [h for h in grade if h > hora_atual]
    
    return [h for h in grade if h not in todos_ocupados]

def buscar_todos_dados_para_painel():
    try:
        valores = planilha_agendamentos.get_all_values()
        if len(valores) == 0:
            return pd.DataFrame()
            
        primeira_celula = str(valores[0][0]).strip().lower()
        tem_cabecalho = primeira_celula in ["nome", "cliente", "client"]
        inicio = 1 if tem_cabecalho else 0
            
        dados_limpos = []
        for linha in valores[inicio:]:
            if len(linha) >= 5:
                nome_val = str(linha[0]).strip()
                tel_val = str(linha[1]).strip()
                data_val = normalizar_data(str(linha[2]))
                hora_val = normalizar_hora(str(linha[3]))
                serv_val = str(linha[4]).strip()
                
                partes_servico = serv_val.split("R$ ")
                valor_val = int(partes_servico[-1].strip()) if len(partes_servico) > 1 and partes_servico[-1].strip().isdigit() else 0
                
                reg_val = str(linha[5]).strip() if len(linha) >= 6 else ""
                
                dados_limpos.append({
                    "Nome": nome_val,
                    "Telefone": tel_val,
                    "Data": data_val,
                    "Hora": hora_val,
                    "Serviço": serv_val,
                    "Valor": valor_val,
                    "Data Registro": reg_val
                })
        return pd.DataFrame(dados_limpos)
    except Exception as e:
        return pd.DataFrame()


# --- MOTOR DE EXPORTAÇÃO EXCEL ESTILIZADO E DINÂMICO ---
def gerar_excel_dashboard(df_dados, lista_servicos, periodo_txt="Filtro Selecionado"):
    output = io.BytesIO()
    wb = openpyxl.Workbook()
    
    charcoal_fill = PatternFill(start_color="1A1D20", end_color="1A1D20", fill_type="solid")
    amber_fill = PatternFill(start_color="D35400", end_color="D35400", fill_type="solid")
    accent_card_fill = PatternFill(start_color="EAECEE", end_color="EAECEE", fill_type="solid")

    font_title = Font(name="Segoe UI", size=15, bold=True, color="FFFFFF")
    font_section = Font(name="Segoe UI", size=12, bold=True, color="1A1D20")
    font_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Segoe UI", size=10, bold=True)
    font_regular = Font(name="Segoe UI", size=10)
    font_kpi_num = Font(name="Segoe UI", size=18, bold=True, color="D35400")
    font_kpi_label = Font(name="Segoe UI", size=9, bold=True, color="566573")

    thin_border_side = Side(border_style="thin", color="BDC3C7")
    thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    double_bottom_border = Border(bottom=Side(border_style="double", color="1A1D20"), top=Side(border_style="thin", color="BDC3C7"))

    # --- ABA 1: RESUMO EXECUTIVO ---
    ws1 = wb.active
    ws1.title = "Resumo Executivo"
    ws1.views.sheetView[0].showGridLines = True
    
    ws1.merge_cells("A1:E2")
    for row in ws1["A1:E2"]:
        for cell in row:
            cell.fill = charcoal_fill
    ws1["A1"] = "BARBEARIA ELITE - DASHBOARD FINANCEIRO"
    ws1["A1"].font = font_title
    ws1["A1"].alignment = Alignment(horizontal="center", vertical="center")
    
    ws1["A3"] = f"Período: {periodo_txt} | Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws1["A3"].font = Font(name="Segoe UI", size=9, italic=True, color="7F8C8D")
    
    ws1.merge_cells("A5:B5")
    ws1["A5"] = "FATURAMENTO ACUMULADO"
    ws1["A5"].font = font_kpi_label
    ws1["A5"].fill = accent_card_fill
    ws1["A5"].alignment = Alignment(horizontal="center")
    
    ws1.merge_cells("A6:B7")
    ws1["A6"] = "=SUM('Faturamento Detalhado'!E2:E2000)"
    ws1["A6"].font = font_kpi_num
    ws1["A6"].fill = accent_card_fill
    ws1["A6"].alignment = Alignment(horizontal="center", vertical="center")
    ws1["A6"].number_format = 'R$ #,##0.00'
    
    ws1.merge_cells("D5:E5")
    ws1["D5"] = "TICKET MÉDIO POR ATENDIMENTO"
    ws1["D5"].font = font_kpi_label
    ws1["D5"].fill = accent_card_fill
    ws1["D5"].alignment = Alignment(horizontal="center")
    
    ws1.merge_cells("D6:E7")
    ws1["D6"] = "=AVERAGE('Faturamento Detalhado'!E2:E2000)"
    ws1["D6"].font = font_kpi_num
    ws1["D6"].fill = accent_card_fill
    ws1["D6"].alignment = Alignment(horizontal="center", vertical="center")
    ws1["D6"].number_format = 'R$ #,##0.00'
    
    for r in range(5, 8):
        for c in [1, 2, 4, 5]:
            ws1.cell(row=r, column=c).border = thin_border
            
    ws1["A9"] = "DESEMPENHO POR SERVIÇO"
    ws1["A9"].font = font_section
    
    headers_res = ["Serviço", "Qtd. Realizada", "Faturamento", "Participação"]
    for c_idx, h_text in enumerate(headers_res, start=1):
        cell = ws1.cell(row=10, column=c_idx, value=h_text)
        cell.font = font_header
        cell.fill = charcoal_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
        
    for idx, (lbl, preco_val) in enumerate(lista_servicos, start=11):
        c_lbl = ws1.cell(row=idx, column=1, value=lbl)
        c_lbl.font = font_regular
        c_lbl.border = thin_border
        
        c_qtd = ws1.cell(row=idx, column=2, value=f"=COUNTIF('Faturamento Detalhado'!D:D, \"*{lbl}*\")")
        c_qtd.font = font_regular
        c_qtd.alignment = Alignment(horizontal="center")
        c_qtd.border = thin_border
        
        c_fat = ws1.cell(row=idx, column=3, value=f"=B{idx}*{preco_val}")
        c_fat.font = font_regular
        c_fat.alignment = Alignment(horizontal="right")
        c_fat.number_format = 'R$ #,##0.00'
        c_fat.border = thin_border
        
        c_pct = ws1.cell(row=idx, column=4, value=f"=C{idx}/$A$6")
        c_pct.font = font_regular
        c_pct.alignment = Alignment(horizontal="center")
        c_pct.number_format = '0.0%'
        c_pct.border = thin_border
        
    total_row = 11 + len(lista_servicos)
    
    ws1.cell(row=total_row, column=1, value="Total Geral").font = font_bold
    ws1.cell(row=total_row, column=1).border = double_bottom_border
    
    ws1.cell(row=total_row, column=2, value=f"=SUM(B11:B{total_row-1})").font = font_bold
    ws1.cell(row=total_row, column=2).alignment = Alignment(horizontal="center")
    ws1.cell(row=total_row, column=2).border = double_bottom_border
    
    ws1.cell(row=total_row, column=3, value=f"=SUM(C11:C{total_row-1})").font = font_bold
    ws1.cell(row=total_row, column=3).alignment = Alignment(horizontal="right")
    ws1.cell(row=total_row, column=3).number_format = 'R$ #,##0.00'
    ws1.cell(row=total_row, column=3).border = double_bottom_border
    
    ws1.cell(row=total_row, column=4, value=f"=SUM(D11:D{total_row-1})").font = font_bold
    ws1.cell(row=total_row, column=4).alignment = Alignment(horizontal="center")
    ws1.cell(row=total_row, column=4).number_format = '0.0%'
    ws1.cell(row=total_row, column=4).border = double_bottom_border

    # --- ABA 2: DETALHADO ---
    ws2 = wb.create_sheet(title="Faturamento Detalhado")
    ws2.views.sheetView[0].showGridLines = True
    
    headers_det = ["Cliente", "WhatsApp", "Data Agendamento", "Serviço", "Valor", "Data Registro"]
    for c_idx, h_text in enumerate(headers_det, start=1):
        cell = ws2.cell(row=1, column=c_idx, value=h_text)
        cell.font = font_header
        cell.fill = amber_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
        
    for r_idx, row in enumerate(df_dados.itertuples(index=False), start=2):
        ws2.cell(row=r_idx, column=1, value=row.Nome).font = font_regular
        ws2.cell(row=r_idx, column=1).border = thin_border
        
        ws2.cell(row=r_idx, column=2, value=row.Telefone).font = font_regular
        ws2.cell(row=r_idx, column=2).alignment = Alignment(horizontal="center")
        ws2.cell(row=r_idx, column=2).border = thin_border
        
        ws2.cell(row=r_idx, column=3, value=row.Data).font = font_regular
        ws2.cell(row=r_idx, column=3).alignment = Alignment(horizontal="center")
        ws2.cell(row=r_idx, column=3).border = thin_border
        
        ws2.cell(row=r_idx, column=4, value=row.Serviço).font = font_regular
        ws2.cell(row=r_idx, column=4).border = thin_border
        
        c_val = ws2.cell(row=r_idx, column=5, value=row.Valor)
        c_val.font = font_regular
        c_val.alignment = Alignment(horizontal="right")
        c_val.number_format = 'R$ #,##0.00'
        c_val.border = thin_border
        
        ws2.cell(row=r_idx, column=6, value=row.Data_Registro if hasattr(row, 'Data_Registro') else "").font = font_regular
        ws2.cell(row=r_idx, column=6).alignment = Alignment(horizontal="center")
        ws2.cell(row=r_idx, column=6).border = thin_border
        
    ultima_linha = len(df_dados) + 1
    total_det_row = ultima_linha + 2
    
    ws2.cell(row=total_det_row, column=4, value="Total Geral").font = font_bold
    ws2.cell(row=total_det_row, column=4).alignment = Alignment(horizontal="right")
    ws2.cell(row=total_det_row, column=4).border = double_bottom_border
    
    c_tot_det = ws2.cell(row=total_det_row, column=5, value=f"=SUM(E2:E{ultima_linha})")
    c_tot_det.font = font_bold
    c_tot_det.alignment = Alignment(horizontal="right")
    c_tot_det.number_format = 'R$ #,##0.00'
    c_tot_det.border = double_bottom_border

    for ws in [ws1, ws2]:
        for col in ws.columns:
            max_len = 0
            for cell in col:
                val_str = str(cell.value or '')
                if len(val_str) > max_len:
                    max_len = len(val_str)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
            
    ws1.column_dimensions['A'].width = 24
    ws1.column_dimensions['B'].width = 16
    ws1.column_dimensions['C'].width = 16
    ws1.column_dimensions['D'].width = 18
    ws1.column_dimensions['E'].width = 16

    wb.save(output)
    return output.getvalue()


# =======================================================
# NAVEGAÇÃO CENTRAL EM TABS (SEM SIDEBAR - 100% RESPONSIVO)
# =======================================================
aba_cliente, aba_barbeiro = st.tabs(["📋 Portal do Cliente", "📊 Painel do Barbeiro (Admin)"])

# =======================================================
# 1. ABA DO CLIENTE (PORTAL DE AGENDAMENTO)
# =======================================================
with aba_cliente:
    st.subheader("✂️ Reserve seu Horário")
    
    # SE O CLIENTE NÃO ESTÁ LOGADO
    if st.session_state["cliente_logado"] is None:
        
        # VERIFICA O FLUXO DE ESQUECI A SENHA
        fluxo = st.session_state["recuperar_senha_fluxo"]
        
        if fluxo["passo"] == "esqueci_senha_solicitar":
            st.write("#### 🔑 Recuperação de Conta")
            st.write("Insira seu número de WhatsApp cadastrado. Enviaremos um código de segurança de 6 dígitos.")
            recup_tel = st.text_input("WhatsApp Cadastrado (Apenas números)", key="recup_tel_input")
            
            col_rec1, col_rec2 = st.columns(2)
            with col_rec1:
                if st.button("✉️ Enviar Código", width="stretch"):
                    tel_limpo = re.sub(r'\D', '', recup_tel)
                    valores = planilha_clientes.get_all_values()
                    encontrou_usuario = False
                    
                    for linha in valores[1:]:
                        if len(linha) >= 2:
                            tel_banco = re.sub(r'\D', '', str(linha[1]))
                            if tel_banco == tel_limpo:
                                encontrou_usuario = True
                                nome_usuario = str(linha[0])
                                # Gera código de 6 dígitos aleatório
                                codigo_gerado = str(random.randint(100000, 999999))
                                
                                st.session_state["recuperar_senha_fluxo"] = {
                                    "passo": "esqueci_senha_validar",
                                    "telefone": tel_limpo,
                                    "codigo": codigo_gerado,
                                    "nome_cliente": nome_usuario
                                }
                                # Envia o código (com simulação de toast para testes)
                                enviar_codigo_recuperacao_whatsapp(nome_usuario, tel_limpo, codigo_gerado)
                                st.success("🎉 Código enviado! Verifique seu WhatsApp.")
                                st.rerun()
                                break
                                
                    if not encontrou_usuario:
                        st.error("❌ Nenhum cliente encontrado com este número de WhatsApp.")
            with col_rec2:
                if st.button("⬅️ Voltar ao Login", width="stretch"):
                    st.session_state["recuperar_senha_fluxo"]["passo"] = "login"
                    st.rerun()
                    
        elif fluxo["passo"] == "esqueci_senha_validar":
            st.write(f"#### 🔒 Validação de Código para: **{fluxo['nome_cliente']}**")
            st.write(f"Digite o código de 6 dígitos enviado para o WhatsApp **{formatar_telefone(fluxo['telefone'])}**.")
            
            # --- CARD DE DEPURADOR PARA TESTES (SÓ EXIBE NO SITE ENQUANTO NÃO HÁ API CONECTADA) ---
            st.info(f"⚙️ **[Modo Desenvolvedor]:** O código gerado para teste é `{fluxo['codigo']}`")
            
            codigo_digitado = st.text_input("Código de 6 dígitos", max_chars=6)
            
            col_val1, col_val2 = st.columns(2)
            with col_val1:
                if st.button("✔️ Confirmar Código", width="stretch"):
                    if codigo_digitado == fluxo["codigo"]:
                        st.session_state["recuperar_senha_fluxo"]["passo"] = "esqueci_senha_redefinir"
                        st.success("Código aceito! Escolha sua nova senha.")
                        st.rerun()
                    else:
                        st.error("❌ Código inválido. Confira e tente novamente.")
            with col_val2:
                if st.button("⬅️ Cancelar", width="stretch"):
                    st.session_state["recuperar_senha_fluxo"] = {"passo": "login", "telefone": "", "codigo": "", "nome_cliente": ""}
                    st.rerun()
                    
        elif fluxo["passo"] == "esqueci_senha_redefinir":
            st.write("#### 🆕 Defina sua Nova Senha")
            nova_senha = st.text_input("Nova Senha", type="password")
            confirmar_nova_senha = st.text_input("Confirme a Nova Senha", type="password")
            
            if st.button("💾 Redefinir Senha", width="stretch"):
                if not nova_senha:
                    st.warning("⚠️ Digite uma senha válida.")
                elif nova_senha != confirmar_nova_senha:
                    st.error("❌ As senhas não conferem!")
                else:
                    if atualizar_senha_cliente(fluxo["telefone"], nova_senha):
                        st.success("🎉 Senha alterada com sucesso! Faça seu login.")
                        st.session_state["recuperar_senha_fluxo"] = {"passo": "login", "telefone": "", "codigo": "", "nome_cliente": ""}
                        st.rerun()
                    else:
                        st.error("Erro interno ao gravar nova senha.")

        # LOGIN PADRÃO / CADASTRO
        else:
            st.info("Acesse sua conta ou cadastre-se para marcar o seu horário.")
            tab_login, tab_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Cadastro"])
            
            with tab_login:
                login_tel = st.text_input("WhatsApp (digite apenas números)", key="login_tel_key")
                login_pass = st.text_input("Sua Senha", type="password", key="login_pass_key")
                
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("🔓 Entrar na Conta", width="stretch"):
                        if not login_tel or not login_pass:
                            st.warning("⚠️ Preencha o WhatsApp e a Senha.")
                        else:
                            perfil = autenticar_cliente(login_tel, login_pass)
                            if perfil:
                                st.session_state["cliente_logado"] = perfil
                                st.success(f"Seja bem-vindo, {perfil['nome']}!")
                                st.rerun()
                            else:
                                st.error("❌ Telefone ou senha incorretos.")
                with col_b2:
                    if st.button("❓ Esqueci a Senha", width="stretch"):
                        st.session_state["recuperar_senha_fluxo"]["passo"] = "esqueci_senha_solicitar"
                        st.rerun()
                        
            with tab_cadastro:
                cad_nome = st.text_input("Seu Nome Completo")
                if cad_nome:
                    cad_nome = re.sub(r'^[=+@-]', '', cad_nome)
                    
                cad_tel = st.text_input("Seu WhatsApp (DDD + Número)")
                cad_insta = st.text_input("Seu Instagram (Opcional - Ex: @carlos_sakai)")
                cad_pass = st.text_input("Crie uma Senha", type="password")
                
                if st.button("✨ Finalizar Cadastro e Entrar", width="stretch"):
                    if not cad_nome or not cad_tel or not cad_pass:
                        st.warning("⚠️ Nome, WhatsApp e Senha são obrigatórios!")
                    else:
                        sucesso, msg = cadastrar_novo_cliente(cad_nome, cad_tel, cad_insta, cad_pass)
                        if sucesso:
                            tel_formatado = formatar_telefone(cad_tel)
                            insta_limpo = cad_insta.replace("@", "").replace(" ", "").strip().lower()
                            
                            st.session_state["cliente_logado"] = {
                                "nome": cad_nome,
                                "telefone": tel_formatado,
                                "rede_social": insta_limpo
                            }
                            st.success("🎉 Cadastro e Login automáticos realizados!")
                            st.rerun()
                        else:
                            st.error(msg)

    # CLIENTE LOGADO -> TELA DE AGENDAMENTO
    else:
        cliente = st.session_state["cliente_logado"]
        
        col_greet1, col_greet2 = st.columns([3, 1])
        with col_greet1:
            st.write(f"### Olá, **{cliente['nome']}**!")
            if cliente['rede_social']:
                st.caption(f"Insta: @{cliente['rede_social']}")
        with col_greet2:
            if st.button("🚪 Sair", width="stretch"):
                st.session_state["cliente_logado"] = None
                st.rerun()

        st.divider()

        if "agendamento_sucesso" in st.session_state:
            dados = st.session_state["agendamento_sucesso"]
            
            st.success(f"🎉 Fechado, {dados['nome']}! Horário reservado para {dados['data']} às {dados['hora']}.")
            st.info(f"O número cadastrado foi {dados['telefone']}.")
            
            st.divider()
            st.write("### 💸 Pagamento")
            tab1, tab2 = st.tabs(["Pagar no Local", "Pagar via PIX"])
            
            with tab1:
                st.write("Tudo certo! Te aguardamos no horário marcado.")
                
            with tab2:
                st.write(f"Valor a pagar: **R$ {dados['preco']}**")
                chave_pix = "suachave@email.com"
                payload_pix = f"00020101021126580014br.gov.bcb.pix0114{chave_pix}520400005303986540{dados['preco']}5802BR5910Barbearia6008Recife62070503***6304"
                
                qr = segno.make(payload_pix)
                buffer_qr = io.BytesIO()
                qr.save(buffer_qr, kind="png", scale=5)
                
                st.image(buffer_qr.getvalue(), caption="Escaneie o QR Code")
                st.code(payload_pix, language="text")
                
            if st.button("Fazer um Novo Agendamento", width="stretch"):
                del st.session_state["agendamento_sucesso"]
                st.rerun()

        else:
            st.text_input("Seu Nome", value=cliente['nome'], disabled=True)
            st.text_input("WhatsApp", value=cliente['telefone'], disabled=True)

            col1, col2 = st.columns(2)
            with col1:
                data = st.date_input("Escolha a data", min_value=pegar_hora_local().date(), format="DD/MM/YYYY")

            opcoes = gerar_horarios_disponiveis(data)

            with col2:
                if opcoes:
                    hora_escolhida = st.selectbox("Escolha o horário", opcoes)
                else:
                    hora_escolhida = None
                    st.error("Agenda lotada para este dia! 🛑")

            servicos_db = obter_servicos()
            opcoes_servicos_cliente = [f"{n} - R$ {p}" for n, p in servicos_db]
            servico = st.selectbox("Serviço", opcoes_servicos_cliente)
            
            preco = servico.split("R$ ")[-1].strip() if servico else "0"

            st.divider()

            if st.button("Confirmar Agendamento", width="stretch"):
                if not hora_escolhida:
                    st.warning("⚠️ Selecione uma data com horários disponíveis.")
                else:
                    data_formatada = data.strftime("%d/%m/%Y")
                    
                    if hora_escolhida in obter_horarios_ocupados(data_formatada):
                        st.error("Putz! Alguém acabou de reservar esse horário. Escolha outro.")
                    else:
                        st.session_state["horarios_bloqueados_sessao"].append((data_formatada, hora_escolhida))

                        registro_now = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
                        planilha_agendamentos.append_row([
                            cliente['nome'], 
                            cliente['telefone'], 
                            f"'{data_formatada}", 
                            f"'{hora_escolhida}", 
                            servico, 
                            registro_now
                        ])
                        
                        st.session_state["agendamento_sucesso"] = {
                            "nome": cliente['nome'],
                            "telefone": cliente['telefone'],
                            "data": data_formatada,
                            "hora": hora_escolhida,
                            "preco": preco
                        }
                        st.rerun()


# =======================================================
# 2. ABA DO BARBEIRO (ADMIN) - LOGIN CENTRALIZADO
# =======================================================
with aba_barbeiro:
    
    # SE O ADMIN NÃO ESTIVER AUTENTICADO
    if not st.session_state["admin_autenticado"]:
        st.subheader("🔐 Área Administrativa")
        st.write("Digite a sua senha de gerenciamento abaixo para ter acesso total ao painel.")
        
        admin_pass = st.text_input("Senha de Administrador", type="password", key="admin_auth_pass_key")
        
        if st.button("🔓 Entrar no Painel", width="stretch"):
            senha_admin_correta_hash = obter_senha_admin_hash()
            if hash_senha(admin_pass) == senha_admin_correta_hash:
                st.session_state["admin_autenticado"] = True
                st.success("Acesso Liberado com Sucesso!")
                st.rerun()
            else:
                st.error("❌ Senha Incorreta. Tente novamente.")
                
    # ADMIN AUTENTICADO -> MOSTRA O SISTEMA DE CONTROLE
    else:
        col_header_adm1, col_header_adm2 = st.columns([3, 1])
        with col_header_adm1:
            st.title("📊 Painel de Controle")
        with col_header_adm2:
            if st.button("🔒 Bloquear Painel (Sair)", width="stretch"):
                st.session_state["admin_autenticado"] = False
                st.rerun()
        
        opcao_painel = st.radio(
            "Selecione uma Tela:",
            ["📋 Fila de Atendimento", "📈 Painel Financeiro & BI", "⚙️ Serviços & Preços", "👥 Clientes Cadastrados", "🔒 Alterar Senha Admin"],
            horizontal=True
        )
        
        st.divider()

        df = buscar_todos_dados_para_painel()

        # --- FILA DE ATENDIMENTO ---
        if opcao_painel == "📋 Fila de Atendimento":
            if df.empty:
                st.warning("Nenhum agendamento encontrado no banco de dados.")
            else:
                data_filtro = st.date_input("Filtrar visualização para a data:", value=pegar_hora_local().date(), format="DD/MM/YYYY")
                data_filtro_str = data_filtro.strftime("%d/%m/%Y")
                
                df_dia = df[df['Data'] == data_filtro_str].copy()
                if not df_dia.empty:
                    df_dia = df_dia.sort_values(by="Hora")
                
                col_res1, col_res2, col_res3 = st.columns(3)
                with col_res1:
                    st.metric("Total de Clientes", len(df_dia))
                with col_res2:
                    faturamento_dia = df_dia['Valor'].sum()
                    st.metric("Faturamento Estimado", f"R$ {faturamento_dia}")
                with col_res3:
                    agora_str = pegar_hora_local().strftime("%H:%M")
                    if not df_dia.empty:
                        pendentes = df_dia[df_dia['Hora'] >= agora_str]
                        proximo = pendentes.iloc[0]['Nome'] if not pendentes.empty else "Finalizado"
                    else:
                        proximo = "-"
                    st.metric("Próximo da Fila", proximo)

                st.divider()
                st.subheader(f"📅 Agenda para {data_filtro_str}")
                
                if df_dia.empty:
                    st.info("Você não tem clientes agendados para esta data.")
                else:
                    for index, row in df_dia.iterrows():
                        with st.container(border=True):
                            c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
                            c1.subheader(f"{row['Hora']}")
                            c2.write(f"**Nome:** {row['Nome']}")
                            c3.write(f"**Serviço:** {row['Serviço']}")
                            
                            num = str(row['Telefone'])
                            limpo = re.sub(r'\D', '', num)
                            if limpo:
                                c4.link_button("📱 WhatsApp", f"https://wa.me/55{limpo}", width="stretch")
                            else:
                                c4.write("Sem telefone")

        # --- PAINEL FINANCEIRO & BI ---
        elif opcao_painel == "📈 Painel Financeiro & BI":
            if df.empty:
                st.warning("Nenhum agendamento encontrado no banco de dados.")
            else:
                st.subheader("📈 Gestão de Caixa e BI")
                
                col_data1, col_data2 = st.columns(2)
                with col_data1:
                    inicio_data = st.date_input("De:", value=pegar_hora_local().date() - timedelta(days=30), format="DD/MM/YYYY")
                with col_data2:
                    fim_data = st.date_input("Até:", value=pegar_hora_local().date() + timedelta(days=15), format="DD/MM/YYYY")
                
                df['Data_dt'] = pd.to_datetime(df['Data'], format='%d/%m/%Y', errors='coerce')
                df_filtrado = df[(df['Data_dt'].dt.date >= inicio_data) & (df['Data_dt'].dt.date <= fim_data)].copy()
                df_filtrado = df_filtrado.sort_values(by="Data_dt")
                
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    total_receita = df_filtrado['Valor'].sum()
                    st.metric("Receita Bruta Total", f"R$ {total_receita:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                with col_f2:
                    total_atendimentos = len(df_filtrado)
                    st.metric("Atendimentos no Período", total_atendimentos)
                with col_f3:
                    ticket_medio = total_receita / total_atendimentos if total_atendimentos > 0 else 0
                    st.metric("Ticket Médio", f"R$ {ticket_medio:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                
                st.divider()
                st.write("### 📥 Extração de Relatório Executivo")
                
                periodo_str = f"De {inicio_data.strftime('%d-%m-%Y')} ate {fim_data.strftime('%d-%m-%Y')}"
                excel_data = gerar_excel_dashboard(df_filtrado, obter_servicos(), periodo_str)
                
                st.download_button(
                    label="📥 Baixar Relatório Financeiro Profissional (Excel)",
                    data=excel_data,
                    file_name=f"Relatorio_Financeiro_{inicio_data.strftime('%Y%m%d')}_{fim_data.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch"
                )
                
                st.divider()
                st.write("### 📊 Gráficos de Desempenho")
                
                if df_filtrado.empty:
                    st.info("Sem dados suficientes para gráficos.")
                else:
                    col_g1, col_g2 = st.columns(2)
                    with col_g1:
                        st.write("**Faturamento Diário (R$)**")
                        st.line_chart(df_filtrado.groupby('Data')['Valor'].sum())
                    with col_g2:
                        st.write("**Participação de Serviços**")
                        st.bar_chart(df_filtrado.groupby('Serviço')['Valor'].sum())

                st.divider()
                with st.expander("Ver Planilha Completa Bruta"):
                    exibicao_df = df.copy()
                    if 'Data_dt' in exibicao_df.columns:
                        exibicao_df = exibicao_df.drop(columns=['Data_dt'])
                    st.dataframe(exibicao_df, use_container_width=True)

        # --- SERVIÇOS & PREÇOS ---
        elif opcao_painel == "⚙️ Serviços & Preços":
            st.subheader("⚙️ Cadastro de Serviços e Preços")
            servicos_atuais = obter_servicos()
            st.dataframe(pd.DataFrame(servicos_atuais, columns=["Serviço", "Preço (R$)"]), use_container_width=True)

            st.write("#### ➕ Adicionar Novo Serviço")
            col_add1, col_add2 = st.columns([2, 1])
            with col_add1:
                novo_nome = st.text_input("Nome do Serviço")
                if novo_nome:
                    novo_nome = novo_nome.replace("-", "").replace("R$", "").strip()
            with col_add2:
                novo_preco = st.number_input("Preço Cobrado (R$)", min_value=0, step=5, value=15)

            if st.button("➕ Confirmar Novo Serviço", width="stretch"):
                if not novo_nome:
                    st.warning("⚠️ Digite o nome do serviço.")
                else:
                    planilha_servicos.append_row([novo_nome, str(novo_preco)])
                    st.success("🎉 Serviço adicionado com sucesso!")
                    st.cache_resource.clear()
                    st.rerun()

            st.divider()
            st.write("#### ✏️ Editar ou Excluir Serviço")
            nomes_opcoes = [s[0] for s in servicos_atuais]
            servico_selecionado = st.selectbox("Selecione para editar:", nomes_opcoes)

            if servico_selecionado:
                preco_atual = next(s[1] for s in servicos_atuais if s[0] == servico_selecionado)
                col_edit1, col_edit2 = st.columns(2)
                with col_edit1:
                    nome_editado = st.text_input("Editar Nome:", value=servico_selecionado)
                    if nome_editado:
                        nome_editado = nome_editado.replace("-", "").replace("R$", "").strip()
                with col_edit2:
                    preco_editado = st.number_input("Editar Preço (R$):", min_value=0, step=5, value=int(preco_atual))

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Salvar Alterações", width="stretch"):
                        valores_brutos = planilha_servicos.get_all_values()
                        for idx_linha, linha in enumerate(valores_brutos, start=1):
                            if idx_linha > 1 and len(linha) >= 1 and linha[0] == servico_selecionado:
                                planilha_servicos.update_cell(idx_linha, 1, nome_editado)
                                planilha_servicos.update_cell(idx_linha, 2, str(preco_editado))
                                st.success("Alterações salvas!")
                                st.cache_resource.clear()
                                st.rerun()
                with col_btn2:
                    if st.button("🗑️ Excluir Serviço Definitivamente", width="stretch"):
                        valores_brutos = planilha_servicos.get_all_values()
                        for idx_linha, linha in enumerate(valores_brutos, start=1):
                            if idx_linha > 1 and len(linha) >= 1 and linha[0] == servico_selecionado:
                                planilha_servicos.delete_rows(idx_linha)
                                st.success("Serviço excluído!")
                                st.cache_resource.clear()
                                st.rerun()

        # --- CLIENTES CADASTRADOS ---
        elif opcao_painel == "👥 Clientes Cadastrados":
            st.subheader("👥 Gestão de Clientes")
            lista_clientes = obter_todos_clientes()
            
            if not lista_clientes:
                st.info("Nenhum cliente cadastrado.")
            else:
                st.dataframe(pd.DataFrame(lista_clientes)[["Nome", "Telefone", "Rede_Social", "Data_Cadastro"]], use_container_width=True)
                
                st.divider()
                for c in lista_clientes:
                    with st.container(border=True):
                        col_c1, col_c2, col_c3 = st.columns([2, 1, 1])
                        with col_c1:
                            st.write(f"👤 **{c['Nome']}**")
                            st.caption(f"Cadastro: {c['Data_Cadastro']}")
                        with col_c2:
                            tel_limpo = re.sub(r'\D', '', c['Telefone'])
                            st.link_button("📱 WhatsApp", f"https://wa.me/55{tel_limpo}", width="stretch")
                        with col_c3:
                            if c['Rede_Social']:
                                st.link_button("📸 Instagram", f"https://instagram.com/{c['Rede_Social']}", width="stretch")
                            else:
                                st.write("Sem Insta")

        # --- ALTERAR SENHA ADMIN (NOVO) ---
        elif opcao_painel == "🔒 Alterar Senha Admin":
            st.subheader("🔒 Segurança do Painel Administrativo")
            st.write("Altere a senha que dá acesso a este painel de controle. A nova senha será salva de forma criptografada na planilha 'Configuracoes'.")
            
            nova_senha_adm = st.text_input("Nova Senha Administrativa", type="password")
            confirmar_senha_adm = st.text_input("Confirme a Nova Senha", type="password")
            
            if st.button("💾 Salvar Nova Senha Admin", width="stretch"):
                if not nova_senha_adm:
                    st.warning("⚠️ Digite uma senha válida.")
                elif nova_senha_adm != confirmar_senha_adm:
                    st.error("❌ As senhas não conferem!")
                else:
                    if atualizar_senha_admin(nova_senha_adm):
                        st.success("🎉 Senha administrativa alterada com sucesso! Utilize-a em seus próximos logins.")
                    else:
                        st.error("Erro interno ao atualizar a senha administrativa no banco.")