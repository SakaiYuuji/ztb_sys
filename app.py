import customtkinter as ctk
import subprocess, sys, threading, os
from datetime import datetime
from functools import partial

# Configuração de tema
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class TacticalHUB(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- NOMES ORIGINAIS RESTAURADOS ---
        self.title("LANÇADOR DE SCRIPTS PYTHON - TACTICAL HUB")
        self.geometry("900x650")
        
        self.neon_blue = "#00f3ff"
        self.neon_green = "#39ff14"

        # Configuração de Grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- LADO ESQUERDO (PAINEL DE BOTÕES) ---
        self.left_side = ctk.CTkFrame(self, width=300, corner_radius=0)
        self.left_side.grid(row=0, column=0, sticky="nsew")
        self.left_side.grid_rowconfigure(7, weight=1)

        # Header Original
        self.logo_label = ctk.CTkLabel(self.left_side, text="INTERFACE OPERACIONAL", 
                                       font=ctk.CTkFont(family="Courier", size=18, weight="bold"),
                                       text_color=self.neon_blue)
        self.logo_label.grid(row=0, column=0, padx=20, pady=30)

        self.setup_buttons()

        # --- LADO DIREITO (TERMINAL E STATUS) ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=1)

        # Painel de Status (O detalhe futurista)
        self.right_panel = ctk.CTkFrame(self.main_container, height=100)
        self.right_panel.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        
        self.time_label = ctk.CTkLabel(self.right_panel, text="", font=("Courier", 14), text_color="#ffffff")
        self.time_label.pack(side="right", padx=20)
        
        self.status_info = ctk.CTkLabel(self.right_panel, 
                                        text="Lançador de Scripts Python",
                                        font=("Courier", 10), text_color="#4f545c")
        self.status_info.pack(side="left", padx=20)

        # Terminal (System Output)
        ctk.CTkLabel(self.main_container, text="[ SYSTEM_OUTPUT ]", 
                     font=("Courier", 10), text_color=self.neon_blue).grid(row=1, column=0, sticky="w")
        
        self.log_area = ctk.CTkTextbox(self.main_container, font=("Consolas", 12),
                                       text_color=self.neon_green, border_width=1, border_color="#1a1a1a")
        self.log_area.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        self.main_container.grid_rowconfigure(2, weight=1)

        self.update_clock()
        self.log("Sistema pronto.")

    def setup_buttons(self):
        # --- LISTA ORIGINAL DE SCRIPTS ---
        scripts = [
            {"label": "> Descompactar Arquivos BMG/ITAU", "arquivo": "organizador_comissao.py"},
            {"label": "> Descompactar Arquivos CREFISA", "arquivo": "organizador_comissao_crefisa.py"},
            {"label": "> Validador Refin", "arquivo": "validador_refin.py"},
            {"label": "> Atualizar Conta", "arquivo": "atualizar_conta.py"},
            {"label": "> Atualizar Tac", "arquivo": "atualiza_tac.py"},
            {"label": "> Consolidador", "arquivo": "consolida 3.1.py"},
            {"label": "> PARCIAIS", "arquivo": "automacao_parcial.py"},
        ]

        for i, s in enumerate(scripts):
            btn = ctk.CTkButton(
                self.left_side,
                text=s["label"], 
                font=("Courier", 12, "bold"),
                text_color=self.neon_blue,
                fg_color="#0a0b12",
                hover_color="#121420",
                anchor="w",
                height=45,
                command=partial(self.executar, s["arquivo"])
            )
            btn.grid(row=i+1, column=0, padx=20, pady=5, sticky="ew")

    def update_clock(self):
        now = datetime.now().strftime("%H:%M:%S")
        self.time_label.configure(text=now)
        self.after(1000, self.update_clock)

    def log(self, mensagem):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_area.insert("end", f"[{timestamp}] : {mensagem}\n")
        self.log_area.see("end")

    def executar(self, arquivo):
        def tarefa():
            self.log(f"Botão acionado: {arquivo}")
            self.log(f"Iniciando conexão com {arquivo}...")

            # 👇 Esconde o launcher
            self.after(0, self.withdraw)

            try:
                proc = subprocess.Popen([sys.executable, arquivo], shell=False)
                proc.wait()
                self.log(f"Processo {arquivo} finalizado.")
            except Exception as e:
                self.log(f"FALHA CRÍTICA: {str(e)}")
            finally:
                # 👇 Traz o launcher de volta
                self.after(0, self.deiconify)

        threading.Thread(target=tarefa, daemon=True).start()

if __name__ == "__main__":
    app = TacticalHUB()
    app.mainloop()
