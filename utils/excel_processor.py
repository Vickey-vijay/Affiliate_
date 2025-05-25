import pandas as pd

class ExcelProcessor:
    def __init__(self, file_path):
        self.df = pd.read_excel(file_path)

    def get_asins(self):
        return self.df["ASIN"].dropna().tolist()
