from flask import Flask, request, render_template
import pandas as pd

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    if file.filename.endswith('.csv'):
        data = pd.read_csv(file)
    elif file.filename.endswith('.xlsx'):
        data = pd.read_excel(file)
    else:
        return 'Unsupported file type', 400
    
    # Converta para JSON para envio ao frontend
    return data.to_json()

if __name__ == '__main__':
    app.run(debug=True)
