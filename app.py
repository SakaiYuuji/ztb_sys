import streamlit as st
import pandas as pd
from datetime import datetime, time
import segno
import io
from google.oauth2.service_account import Credentials
import gspread

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Barbearia Elite - Agendamento", layout="centered")

# --- CONEXÃO COM GOOGLE SHEETS ---
try:
    # Transforma os segredos em dicionário
    creds_dict = dict(st.secrets["gcp_service_account"])

    # Limpeza e normalização da chave privada para evitar erros de formatação/PEM
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

    # Cria os cabeçalhos caso a planilha esteja completamente em branco
    if not planilha.get_all_values():
        planilha.append_row(["Nome", "Telefone", "Data", "Hora", "Servico", "Data Registro"])

except Exception as e:
    st.error(f"Erro na conexão com o Banco de Dados/Sheets: {e}")
    st.stop()


# --- FUNÇÕES DE AUXÍLIO ---
def verificar_disponibilidade(data_selecionada, hora_selecionada):
    """Verifica se já existe um agendamento para a data e hora informadas"""
    registros = planilha.get_all_records()
    for reg in registros:
        if str(reg.get("Data")) == str(data_selecionada) and str(reg.get("Hora")) == str(hora_selecionada):
            return False
    return True

def salvar_agendamento(nome, telefone, data, hora, servico):
    """Insere uma nova linha de agendamento na planilha"""
    registro_data = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    planilha.append_row([nome, telefone, str(data), str(hora), servico, registro_data])


# --- INTERFACE WEB (Streamlit) ---
st.title("✂️ Barbearia Elite")
st.subheader("Agende seu horário em segundos")

with st.form("agendamento_form"):
    nome = st.text_input("Seu Nome Completo")
    telefone = st.text_input("WhatsApp (com DDD)")
    
    col1, col2 = st.columns(2)
    with col1:
        data = st.date_input("Escolha a data", min_value=datetime.today().date())
    with col2:
        hora = st.time_input("Escolha o horário", value=time(9, 0))
        
    servico = st.selectbox("Serviço", ["Corte Simples - R$ 30", "Barba - R$ 20", "Combo - R$ 45"])
    preco = servico.split("R$ ")[1]

    submit = st.form_submit_button("Confirmar Agendamento")

# --- LÓGICA DE PROCESSAMENTO ---
if submit:
    if nome and telefone:
        # Formata a hora para HH:MM e data para DD/MM/AAAA para salvar padronizado
        hora_formatada = hora.strftime("%H:%M")
        data_formatada = data.strftime("%d/%m/%Y")
        
        # 1. Validação de horário ocupado
        if verificar_disponibilidade(data_formatada, hora_formatada):
            # 2. Grava na planilha
            salvar_agendamento(nome, telefone, data_formatada, hora_formatada, servico)
            
            st.success(f"🎉 Horário reservado com sucesso para {data_formatada} às {hora_formatada}!")
            
            # --- PAGAMENTO PIX ---
            st.divider()
            st.write("### 💸 Pagamento")
            tab1, tab2 = st.tabs(["Pagar no Local", "Pagar via PIX"])
            
            with tab1:
                st.info("Tudo certo! Te esperamos na barbearia. O pagamento será feito após o atendimento.")
                
            with tab2:
                st.write(f"Valor: R$ {preco}")
                
                # Configuração do PIX (Substitua pela sua chave)
                chave_pix = "suachave@email.com"
                payload_pix = f"00020101021126580014br.gov.bcb.pix0114{chave_pix}520400005303986540{preco}5802BR5910Barbearia6008Recife62070503***6304"
                
                # Gera o QR Code em buffer de memória para evitar dependência do Pillow (PIL)
                qr = segno.make(payload_pix)
                buffer_qr = io.BytesIO()
                qr.save(buffer_qr, kind="png", scale=5)
                
                st.image(buffer_qr.getvalue(), caption="Escaneie o QR Code para pagar")
                st.code(payload_pix, language="text")
                st.caption("ℹ️ Após realizar o pagamento, envie o comprovante de transferência para o nosso WhatsApp.")
        else:
            st.error(f"⚠️ O horário de {hora_formatada} no dia {data_formatada} já está ocupado. Por favor, escolha outro horário.")
    else:
        st.error("Por favor, preencha todos os campos obrigatórios (Nome e Telefone).")
