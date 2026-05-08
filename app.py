import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import segno
import io
from google.oauth2.service_account import Credentials
import gspread
import re

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Barbearia Elite - Agendamento", layout="centered")

# --- CONEXÃO COM GOOGLE SHEETS ---
@st.cache_resource
def conectar_planilha():
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

    # Nome exato da planilha que você acabou de criar no Google Drive
    NOME_PLANILHA = "13UgvP4l2EhgBNON2YGTALe8cwDXO5zCwgQzkynnwkk8" 
    planilha = client.open_by_key(NOME_PLANILHA).sheet1

    return planilha

try:
    planilha = conectar_planilha()
except Exception as e:
    st.error(f"Erro na conexão: {e}")
    st.stop()


# --- FUNÇÕES DE LÓGICA E BLINDAGEM ---

def pegar_hora_local():
    """Garante que o horário seja sempre o local (UTC-3), ignorando o fuso do servidor web"""
    return datetime.utcnow() - timedelta(hours=3)

def formatar_telefone(numero_cru):
    """Pega os números e mascara no padrão (81) 9 9696-2824"""
    # Extrai apenas os dígitos do que o cliente digitou
    numeros = re.sub(r'\D', '', numero_cru)
    
    if len(numeros) == 11: # Celular com 9 extra
        return f"({numeros[:2]}) {numeros[2]} {numeros[3:7]}-{numeros[7:]}"
    elif len(numeros) == 10: # Fixo ou sem o 9
        return f"({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}"
    
    # Se o cliente digitar algo fora do padrão, retorna do jeito que ele fez
    return numero_cru

def obter_horarios_ocupados(data_str):
    """Busca na planilha os horários já agendados e limpa a formatação"""
    try:
        registros = planilha.get_all_records()
        ocupados = []
        for reg in registros:
            # Remove o apóstrofo e espaços extras da data e hora
            reg_data = str(reg.get("Data", "")).replace("'", "").strip()
            reg_hora = str(reg.get("Hora", "")).strip()
            
            # Padroniza para HH:MM (pega apenas os 5 primeiros caracteres)
            if len(reg_hora) >= 5:
                reg_hora = reg_hora[:5]
                
            if reg_data == data_str:
                ocupados.append(reg_hora)
        return ocupados
    except:
        return []

def gerar_horarios_disponiveis(data_selecionada):
    """Gera a grade de 30min e remove o que já está ocupado"""
    todos_horarios = []
    inicio = datetime.strptime("08:00", "%H:%M")
    fim = datetime.strptime("18:30", "%H:%M")
    
    atual = inicio
    while atual <= fim:
        todos_horarios.append(atual.strftime("%H:%M"))
        atual += timedelta(minutes=30)
    
    # Busca o que já existe no Sheets para o dia selecionado
    data_str = data_selecionada.strftime("%d/%m/%Y")
    ocupados = obter_horarios_ocupados(data_str)
    
    # A MÁGICA: Só mantém na lista o que NÃO está nos ocupados
    disponiveis = [h for h in todos_horarios if h not in ocupados]
    
    return disponiveis

def salvar_agendamento(nome, telefone, data, hora, servico):
    """Salva com o apóstrofo invisível para blindar a formatação"""
    registro_data = pegar_hora_local().strftime("%d/%m/%Y %H:%M:%S")
    # O f"'{var}" garante que o Sheets salve como TEXTO
    planilha.append_row([nome, telefone, f"'{data}", f"'{hora}", servico, registro_data])


# --- ÁREA ADMINISTRATIVA (ESCONDIDA NO MENU LATERAL) ---
with st.sidebar:
    st.header("⚙️ Acesso Admin")
    admin_pass = st.text_input("Senha de Gerenciamento", type="password")
    
    if admin_pass == "12345":  # Mude para uma senha segura depois
        st.success("Acesso Liberado!")
        st.write("Aqui você poderá ajustar regras no futuro.")
        novo_corte = st.number_input("Valor do Corte Simples (R$)", value=30)
        # Mais para frente podemos usar esses inputs para salvar configurações numa aba "Config" do Sheets.
    elif admin_pass:
        st.error("Senha Incorreta")


# --- INTERFACE DO CLIENTE ---
st.title("✂️ Barbearia Elite")
st.subheader("Agende seu horário")

# Como tiramos o st.form, as variáveis atualizam a tela imediatamente
nome = st.text_input("Seu Nome Completo")
telefone_input = st.text_input("WhatsApp (digite apenas números, ex: 81996962824)", max_chars=11)

col1, col2 = st.columns(2)

with col1:
    # O format "DD/MM/YYYY" ajusta a exibição, e min_value bloqueia o passado
    data = st.date_input(
        "Escolha a data", 
        min_value=pegar_hora_local().date(), 
        format="DD/MM/YYYY"
    )

with col2:
    horarios_disponiveis = gerar_horarios_disponiveis(data)
    
    if horarios_disponiveis:
        hora = st.selectbox("Escolha o horário", horarios_disponiveis)
    else:
        hora = None
        st.error("Agenda lotada para este dia! 🛑")

servico = st.selectbox("Serviço", ["Corte Simples - R$ 30", "Barba - R$ 20", "Combo - R$ 45"])
preco = servico.split("R$ ")[1]

st.divider()

# Botão de envio avulso
if st.button("Confirmar Agendamento", use_container_width=True):
    if not nome or not telefone_input:
        st.warning("⚠️ Preencha seu nome e telefone para continuar.")
    elif not hora:
        st.warning("⚠️ Selecione uma data com horários disponíveis.")
    else:
        # Formata o telefone e a data antes de salvar
        telefone_formatado = formatar_telefone(telefone_input)
        data_formatada = data.strftime("%d/%m/%Y")
        
        # Checagem de segurança dupla (caso dois clientes abram o app ao mesmo tempo)
        ocupados_agora = obter_horarios_ocupados(data_formatada)
        if hora in ocupados_agora:
            st.error("Putz! Alguém acabou de reservar esse horário enquanto você preenchia. Escolha outro horário.")
        else:
            # Salva na planilha
            salvar_agendamento(nome, telefone_formatado, data_formatada, hora, servico)
            
            st.success(f"🎉 Fechado, {nome}! Horário reservado para {data_formatada} às {hora}.")
            st.info(f"O número cadastrado foi {telefone_formatado}.")
            
            # --- ÁREA DO PIX ---
            st.write("### 💸 Pagamento")
            tab1, tab2 = st.tabs(["Pagar no Local", "Pagar via PIX"])
            
            with tab1:
                st.write("Pode acertar na hora do atendimento. Te esperamos lá!")
                
            with tab2:
                st.write(f"Valor a pagar: **R$ {preco}**")
                
                chave_pix = "suachave@email.com"
                payload_pix = f"00020101021126580014br.gov.bcb.pix0114{chave_pix}520400005303986540{preco}5802BR5910Barbearia6008Recife62070503***6304"
                
                qr = segno.make(payload_pix)
                buffer_qr = io.BytesIO()
                qr.save(buffer_qr, kind="png", scale=5)
                
                st.image(buffer_qr.getvalue(), caption="Escaneie o QR Code no app do seu banco")
                st.code(payload_pix, language="text")
