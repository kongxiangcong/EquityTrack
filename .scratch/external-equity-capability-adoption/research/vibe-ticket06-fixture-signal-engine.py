import pandas as pd


class SignalEngine:
    def generate(self, data_map):
        signals = {}
        for code, frame in data_map.items():
            signal = pd.Series(0.0, index=frame.index)
            for index in range(len(signal)):
                signal.iloc[index] = 1.0 if index % 4 in (0, 1) else 0.0
            signals[code] = signal
        return signals
