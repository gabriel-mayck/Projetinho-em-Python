import re
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

import requests
from bs4 import BeautifulSoup

PRAZO_DIAS, MULTA_DIA = 7, 1.50   # prazo para devolver (dias) e multa (R$) por dia de atraso

BG, PAINEL, CAMPO, FG, CINZA, DESTAQUE = "#1e1e2e", "#2a2a3d", "#33334a", "#e6e6ef", "#a0a0b8", "#4f8cff"
CARDS_POR_LINHA = 5


# ============================= MODELO (as regras do sistema) =============================
class Livro:
    def __init__(self, codigo, titulo, autor):
        self.codigo, self.titulo, self.autor = codigo, titulo,  autor
        self.disponivel = True

class Usuario:
    def __init__(self, matricula, nome):
        self.matricula, self.nome = matricula, nome

class Emprestimo:
    # liga o livro ao usuario (é a classe "relacionada": ela guarda um Livro e um Usuario)

    def __init__(self, livro, usuario):
        self.livro, self.usuario = livro, usuario
        self.data_emprestimo = date.today()
        self.data_prevista = self.data_emprestimo + timedelta(days=PRAZO_DIAS)
        self.data_devolucao = None
        livro.disponivel = False

    def calcular_multa(self):
        # multa = dias de atraso x valor da multa por dia
        ref = self.data_devolucao or date.today()
        return max((ref - self.data_prevista).days, 0) * MULTA_DIA

    def devolver(self, data=None):
        self.data_devolucao = data or date.today()
        self.livro.disponivel = True
        return self.calcular_multa()


# ---- BIBLIOTECA (guarda tudo e valida as ações) ----
class Biblioteca:
    """Guarda tudo (livros, usuários, empréstimos) e valida as ações."""

    def __init__(self):
        self.livros, self.usuarios, self.emprestimos = {}, {}, []
    def cadastrar_livro(self, codigo, titulo, autor):
        if not (codigo and titulo and autor):
            raise ValueError("Preencha todos os campos do livro.")
        if codigo in self.livros:
            raise ValueError("Já existe um livro com esse código.")
        self.livros[codigo] = Livro(codigo, titulo, autor)

    def cadastrar_usuario(self, matricula, nome):
        if not (matricula and nome):
            raise ValueError("Preencha todos os campos do usuário.")
        if matricula in self.usuarios:
            raise ValueError("Já existe um usuário com essa matrícula.")
        self.usuarios[matricula] = Usuario(matricula, nome)

    def remover_livro(self, codigo):
        if not self.livros[codigo].disponivel:
            raise ValueError("Não dá para remover: livro está emprestado.")
        del self.livros[codigo]

    def remover_usuario(self, matricula):
        if any(e.usuario.matricula == matricula and not e.data_devolucao for e in self.emprestimos):
            raise ValueError("Não dá para remover: usuário tem livro emprestado.")
        del self.usuarios[matricula]

    def emprestar(self, codigo, matricula):
        livro, usuario = self.livros.get(codigo), self.usuarios.get(matricula)
        if not livro or not usuario:
            raise ValueError("Selecione um livro e um usuário.")
        if not livro.disponivel:
            raise ValueError("Livro já está emprestado.")
        emp = Emprestimo(livro, usuario)
        self.emprestimos.append(emp)
        return emp

    def devolver(self, emprestimo, data=None):
        if emprestimo.data_devolucao:
            raise ValueError("Esse empréstimo já foi devolvido.")
        return emprestimo.devolver(data)

# ============================ WEB SCRAPING ===============================
class BuscadorLivros:
    """Web scraping na Wikipédia (pt): 1) baixa o HTML  2) lê com BeautifulSoup
    3) pega o resumo (1º parágrafo) e os dados da caixa de informações."""
    SITE = "https://pt.wikipedia.org"
    # Só mostramos na janelinha os dados da caixa de informações que começam com estas palavras
    DADOS = ("Autor", "Gênero", "Género", "País", "Idioma", "Língua",
             "Lançamento", "Publicação", "Páginas", "Editora")

    def baixar(self, url, parametros=None):
        try:
            r = requests.get(url, params=parametros, timeout=10,
                             headers={"User-Agent": "BibliotecaEscolar/1.0 (projeto de faculdade)"})
            r.raise_for_status()
        except requests.RequestException:
            raise ValueError("Não foi possível acessar o site. Verifique a internet.")
        return BeautifulSoup(r.text, "html.parser"), r.url

    def limpar(self, texto):
        # tira as notas de rodapé, ex.: [1], e espaços sobrando
        return re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", "", texto)).strip()


    def buscar(self, titulo):
        #  1 Pesquisa o título na Wikipédia
        sopa, link = self.baixar(self.SITE + "/w/index.php", {"search": titulo})
        primeiro = sopa.select_one(".mw-search-result-heading a")   # lista de resultados? abre o 1º
        if primeiro:
            sopa, link = self.baixar(self.SITE + primeiro["href"])
        cabecalho = sopa.select_one("#firstHeading")
        if cabecalho is None or sopa.select_one(".mw-search-nonefound"):
            raise ValueError("Nenhuma informação encontrada para esse título.")


        # PASSO 2: resumo = primeiro parágrafo com mais de 60 letras
        sinopse = "Resumo não disponível."                          # 1º parágrafo grande da página
        for p in sopa.select("#mw-content-text .mw-parser-output > p"):
            texto = self.limpar(p.get_text())
            if len(texto) > 60:
                sinopse = texto[:700] + ("..." if len(texto) > 700 else "")
                break


        # PASSO 3: dados da caixa de informações (Autor, Gênero, País...)
        detalhes = []                                               # caixa de informações (Autor, Gênero...)
        for linha in sopa.select("table.infobox tr"):
            rotulo, valor = linha.find("th"), linha.find("td")
            if rotulo and valor and self.limpar(rotulo.get_text(" ")).startswith(self.DADOS):
                detalhes.append((self.limpar(rotulo.get_text(" ")), self.limpar(valor.get_text(" "))))
        return {"titulo": cabecalho.get_text(strip=True), "sinopse": sinopse, "detalhes": detalhes, "link": link}


# ================================== TELAS ======================================
def label(pai, texto, bg=BG, fg=FG, **opcoes):
    return tk.Label(pai, text=texto, bg=bg, fg=fg, **opcoes)


def resumir(texto, limite):
    """Corta textos grandes e coloca '…' no final (para os cards ficarem iguais)."""
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


class App(tk.Tk):               # App É a janela principal (herda de tk.Tk)
    def __init__(self):
        super().__init__()
        self.title("Sistema de Biblioteca")
        self.geometry("960x600")
        self.aplicar_tema_escuro()
        self.bib, self.buscador = Biblioteca(), BuscadorLivros()

        # ============== DADOS DE EXEMPLO, aparece quando o programa abre==================
        self.bib.cadastrar_livro("L1", "Dom Casmurro", "Machado de Assis")
        self.bib.cadastrar_livro("L2", "O Cortiço", "Aluísio Azevedo")
        self.bib.cadastrar_livro("L3", "As Cronicas de Narnia", "C. S. Lewis")

        self.bib.cadastrar_usuario("U1", "Gabriel Mayck")
        self.bib.cadastrar_usuario("U2", "Italo Pereira")
        self.bib.cadastrar_usuario("U3", "Lucas Rock")

        # ---- ABAS (Livros / Usuários / Empréstimos) ----
        abas = ttk.Notebook(self)
        abas.pack(fill="both", expand=True, padx=8, pady=8)
        self.aba_livros, self.aba_usuarios, self.aba_emprestimos = [ttk.Frame(abas) for _ in range(3)]
        for aba, nome in ((self.aba_livros, "Livros"), (self.aba_usuarios, "Usuários"),
                          (self.aba_emprestimos, "Empréstimos")):

            abas.add(aba, text=nome)
        self.montar_livros() # desenha o conteúdo de cada aba
        self.montar_usuarios()
        self.montar_emprestimos()
        self.atualizar() # preenche tabelas e cards com os dados


    # =================== TEMA ESCURO =================
    def aplicar_tema_escuro(self):
        self.configure(bg=BG)
        st = ttk.Style(self)
        st.theme_use("clam")

        # tema que aceita mudar as cores
        st.configure(".", background=BG, foreground=FG, fieldbackground=CAMPO, bordercolor=PAINEL,
                     lightcolor=PAINEL, darkcolor=PAINEL, troughcolor=PAINEL, font=("Segoe UI", 10))
        st.configure("TNotebook", background=BG, borderwidth=0)                                               # barra das abas
        st.configure("TNotebook.Tab", background=PAINEL, foreground=FG, padding=(14, 6))                      # cada aba
        st.configure("TButton", background=PAINEL, foreground=FG, padding=5)                                  # botões
        st.configure("TEntry", fieldbackground=CAMPO, foreground=FG, insertcolor=FG)                          # caixinhas de texto
        st.configure("TCombobox", fieldbackground=CAMPO, background=PAINEL, foreground=FG, arrowcolor=FG)     # listas suspensas
        st.configure("Treeview", background=PAINEL, fieldbackground=PAINEL, foreground=FG, rowheight=26, borderwidth=0)   # tabelas
        st.configure("Treeview.Heading", background=BG, foreground=FG, relief="flat", font=("Segoe UI", 10, "bold")) # cabeçalho

        # >>>>>> ESTE LAÇO É O QUE DEIXA AZUL (DESTAQUE) <<<<<<
        # cor azul quando o item está selecionado / com o mouse em cima
        for estilo, estado in (("TNotebook.Tab", "selected"), ("TButton", "active"), ("Treeview", "selected")):
            st.map(estilo, background=[(estado, DESTAQUE)], foreground=[(estado, "white")])


            # Combobox (lista suspensa de Livro/Usuário na aba Empréstimos): mantém o fundo escuro
        st.map("TCombobox", fieldbackground=[("readonly", CAMPO)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", CAMPO)], selectforeground=[("readonly", FG)])

        # cores da lista que abre no combobox
        for opcao, cor in (("background", CAMPO), ("foreground", FG), ("selectBackground", DESTAQUE)):
            self.option_add(f"*TCombobox*Listbox.{opcao}", cor)


    # ================= FUNÇÕES AUXILIARES ========================
    def campo(self, pai, rotulo, col):
        """Cria um rótulo + caixinha de texto lado a lado."""
        ttk.Label(pai, text=rotulo).grid(row=0, column=col * 2, padx=4, pady=6)
        e = ttk.Entry(pai, width=18)
        e.grid(row=0, column=col * 2 + 1, padx=4)
        return e

    def tabela(self, pai, colunas):
        """Cria uma tabela (usada em Usuários e Empréstimos)."""
        t = ttk.Treeview(pai, columns=colunas, show="headings", height=12)
        for c in colunas:
            t.heading(c, text=c)
            t.column(c, width=110)
        t.pack(fill="both", expand=True, padx=6, pady=6)
        return t

    def cadastrar(self, funcao, entradas):
        """Chama a função de cadastro com o texto das caixinhas; se der certo, limpa as caixinhas."""
        try:
            funcao(*[e.get().strip() for e in entradas])
        except ValueError as erro:
            return messagebox.showwarning("Atenção", str(erro))
        for e in entradas:
            e.delete(0, "end")
        self.atualizar()

    def remover(self, pergunta, funcao, chave):
        """Pergunta Sim/Não e, se for Sim, chama a função de remoção."""
        if not messagebox.askyesno("Confirmar", pergunta):   # caixinha de Sim/Não (return, "nao" nao acontece nada)
            return
        try:
            funcao(chave)
        except ValueError as erro:
            return messagebox.showwarning("Atenção", str(erro))
        self.atualizar()

    # ================= JANELA / CAMPOS: LIVROS =================
    def montar_livros(self):
        f = ttk.Frame(self.aba_livros)
        f.pack(fill="x")
        entradas = [self.campo(f, nome, i) for i, nome in enumerate(("Código", "Título", "Autor"))]
        ttk.Button(f, text="Cadastrar", command=lambda: self.cadastrar(self.bib.cadastrar_livro, entradas)
                   ).grid(row=0, column=6, padx=6)

        # área com barra de rolagem onde ficam os cards
        area = ttk.Frame(self.aba_livros)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0)
        barra = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.frame_cards = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame_cards, anchor="nw")
        self.frame_cards.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))


    # ================= JANELA / ABA: USUÁRIOS =================
    def montar_usuarios(self):
        f = ttk.Frame(self.aba_usuarios)
        f.pack(fill="x")
        entradas = [self.campo(f, nome, i) for i, nome in enumerate(("Matrícula", "Nome"))]
        ttk.Button(f, text="Cadastrar", command=lambda: self.cadastrar(self.bib.cadastrar_usuario, entradas)
                   ).grid(row=0, column=4, padx=6)
        ttk.Button(f, text="Remover selecionado", command=self.del_usuario).grid(
            row=1, column=0, columnspan=2, padx=6, pady=2, sticky="w")
        self.t_usuarios = self.tabela(self.aba_usuarios, ("Matrícula", "Nome"))


    # ================= JANELA / ABA: EMPRÉSTIMOS =================
    def montar_emprestimos(self):
        f = ttk.Frame(self.aba_emprestimos)
        f.pack(fill="x")
        ttk.Label(f, text="Livro").grid(row=0, column=0, padx=4, pady=6)
        self.cb_livro = ttk.Combobox(f, width=24, state="readonly")
        self.cb_livro.grid(row=0, column=1)
        ttk.Label(f, text="Usuário").grid(row=0, column=2, padx=4)
        self.cb_user = ttk.Combobox(f, width=20, state="readonly")
        self.cb_user.grid(row=0, column=3)
        ttk.Button(f, text="Emprestar", command=self.add_emprestimo).grid(row=0, column=4, padx=6)

        f2 = ttk.Frame(self.aba_emprestimos)
        f2.pack(fill="x")
        ttk.Label(f2, text="Data devolução (dd/mm/aaaa, vazio = hoje)").grid(row=0, column=0, padx=4)
        self.e_data = ttk.Entry(f2, width=12)             # caixinha da data (vazia = devolve hoje)
        self.e_data.grid(row=0, column=1)
        ttk.Button(f2, text="Devolver selecionado", command=self.devolver).grid(row=0, column=2, padx=6)

        # ============= TABELA DE INFORMAÇÕES DE EMPRESTIMOS ==================
        self.t_emp = self.tabela(self.aba_emprestimos,
                                 ("Livro", "Usuário", "Empréstimo", "Prevista", "Devolução", "Multa"))


    # ================= CARDS DOS LIVROS (e os ÍCONES) =================
    def desenhar_cards(self):
        for w in self.frame_cards.winfo_children():   # apaga os cards antigos e desenha tudo de novo
            w.destroy()
        for i, livro in enumerate(self.bib.livros.values()):
            card = tk.Frame(self.frame_cards, bg=PAINEL, padx=8, pady=8)
            card.grid(row=i // CARDS_POR_LINHA, column=i % CARDS_POR_LINHA, padx=8, pady=8, sticky="n")

            # "capa" do card (quadro com ícone de livro, tamanho fixo)
            capa = tk.Frame(card, bg=CAMPO, width=120, height=110)
            capa.pack_propagate(False)
            capa.pack()
            label(capa, "📖", CAMPO, font=("Segoe UI Emoji", 35)).pack(expand=True)


            # width/height fixos (em caracteres/linhas) deixam todos os cards iguais
            label(card, resumir(livro.titulo, 36), PAINEL, width=16, height=2, wraplength=120,
                  font=("Segoe UI", 10, "bold")).pack(pady=(6, 0))
            label(card, resumir(livro.autor, 22), PAINEL, CINZA, width=16, height=2, wraplength=120).pack()
            if livro.disponivel:
                label(card, "Disponível", PAINEL, "#4caf50").pack()    # verde
            else:
                label(card, "Emprestado", PAINEL, "#ef5350").pack()    # vermelho

            # ==============ÍCONES DOS BOTÕES: (pesquisar) e (remover)============
            ttk.Button(card, text="🔍 Pesquisar na web",
                       command=lambda livro=livro: self.buscar_web(livro)).pack(fill="x", pady=(6, 2))
            ttk.Button(card, text="🗑 Remover", command=lambda livro=livro: self.remover(
                f'Deseja remover o livro "{livro.titulo}"?', self.bib.remover_livro, livro.codigo)).pack(fill="x")


    # ================= JANELINHA COM AS INFORMAÇÕES DO LIVRO =================
    def mostrar_info(self, info):
        janela = tk.Toplevel(self, bg=BG, padx=16, pady=16)
        janela.title("Informações do livro")
        janela.transient(self)   # fica na frente da janela principal
        txt = dict(wraplength=460, justify="left")
        label(janela, info["titulo"], font=("Segoe UI", 14, "bold"), **txt).pack(anchor="w")
        for rotulo, valor in info["detalhes"]:   # autor, gênero, país, idioma...
            label(janela, f"{rotulo}: {valor}", **txt).pack(anchor="w")
        label(janela, "Sobre o livro", fg=DESTAQUE, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        label(janela, info["sinopse"], **txt).pack(anchor="w")
        label(janela, f"Fonte: {info['link']}", fg=CINZA, **txt).pack(anchor="w", pady=(12, 0))
        ttk.Button(janela, text="Fechar", command=janela.destroy).pack(pady=(12, 0))


    # ================= Ação dos Botões =================
    def buscar_web(self, livro):
        self.config(cursor="watch")   # mostra o "relógio" do mouse enquanto busca
        self.update_idletasks()
        try:
            info = self.buscador.buscar(livro.titulo)
        except ValueError as erro:
            return messagebox.showwarning("Atenção", str(erro))
        finally:
            self.config(cursor="")
        self.mostrar_info(info)

    def del_usuario(self):
        sel = self.t_usuarios.selection()
        if not sel:
            return messagebox.showwarning("Atenção", "Selecione um usuário na tabela.")
        self.remover("Remover o usuário selecionado?", self.bib.remover_usuario, sel[0])

    def add_emprestimo(self):
        try:
            cod = self.cb_livro.get().split(" - ")[0]
            mat = self.cb_user.get().split(" - ")[0]
            emp = self.bib.emprestar(cod, mat)
        except ValueError as erro:
            return messagebox.showwarning("Atenção", str(erro))
        messagebox.showinfo("Ok", f"Devolver até {emp.data_prevista:%d/%m/%Y}.")
        self.atualizar()

    def devolver(self):
        sel = self.t_emp.selection()
        if not sel:
            return messagebox.showwarning("Atenção", "Selecione um empréstimo.")
        texto = self.e_data.get().strip()
        try:
            data = datetime.strptime(texto, "%d/%m/%Y").date() if texto else None
            multa = self.bib.devolver(self.bib.emprestimos[int(sel[0])], data)
        except ValueError as erro:
            return messagebox.showwarning("Atenção", str(erro) if texto == "" or "já" in str(erro) else "Data inválida.")
        messagebox.showinfo("Devolvido", f"Multa: R$ {multa:.2f}")
        self.atualizar()

    # ================= ATUALIZA TUDO NA TELA =================
    def atualizar(self):
        self.desenhar_cards()
        for t in (self.t_usuarios, self.t_emp):
            t.delete(*t.get_children())
        for u in self.bib.usuarios.values():
            self.t_usuarios.insert("", "end", iid=u.matricula, values=(u.matricula, u.nome))
        for i, e in enumerate(self.bib.emprestimos):
            dev = f"{e.data_devolucao:%d/%m/%Y}" if e.data_devolucao else "-"
            self.t_emp.insert("", "end", iid=str(i), values=(
                e.livro.titulo, e.usuario.nome, f"{e.data_emprestimo:%d/%m/%Y}",
                f"{e.data_prevista:%d/%m/%Y}", dev, f"R$ {e.calcular_multa():.2f}"))
        self.cb_livro["values"] = [f"{l.codigo} - {l.titulo}" for l in self.bib.livros.values() if l.disponivel]
        self.cb_user["values"] = [f"{u.matricula} - {u.nome}" for u in self.bib.usuarios.values()]


if __name__ == "__main__":
    App().mainloop()
