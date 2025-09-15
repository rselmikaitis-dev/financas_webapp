import sqlite3

def init_db():
    conn = sqlite3.connect("data.db", check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contas (
            id INTEGER PRIMARY KEY,
            nome TEXT UNIQUE,
            dia_vencimento INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY,
            nome TEXT UNIQUE,
            tipo TEXT DEFAULT 'Despesa Variável'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subcategorias (
            id INTEGER PRIMARY KEY,
            categoria_id INTEGER,
            nome TEXT,
            UNIQUE(categoria_id, nome),
            FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            date TEXT,
            description TEXT,
            value REAL,
            account TEXT,
            subcategoria_id INTEGER,
            status TEXT DEFAULT 'final',
            FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id)
        )
    """)
    conn.commit()

    # Categoria Transferências
    cursor.execute(
        "INSERT OR IGNORE INTO categorias (nome, tipo) VALUES (?, ?)",
        ("Transferências", "Neutra")
    )
    conn.commit()
    cursor.execute("SELECT id FROM categorias WHERE nome='Transferências'")
    cat_id = cursor.fetchone()[0]
    cursor.execute(
        "INSERT OR IGNORE INTO subcategorias (categoria_id, nome) VALUES (?, ?)",
        (cat_id, "Entre contas")
    )
    conn.commit()

    return conn, cursor
