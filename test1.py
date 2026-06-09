import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import nsw                              # brings `nsw` itself into scope
from nsw.loader import load_data        # brings `load_data` directly into scope

print("nsw version:", nsw.__version__)

data1 = load_data("NIFTY", "1m")

print(data1.head())

print("\n\n\n")

print(data1.tail())

print("\n\n\n")

print(data1.describe())


plt.plot(range(len(data1)), data1["close"], marker="o", markersize=3, linestyle="-")
plt.show()

