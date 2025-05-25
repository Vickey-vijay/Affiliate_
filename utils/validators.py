class Validator:
    @staticmethod
    def is_valid_asin(asin):
        return isinstance(asin, str) and len(asin) == 10
