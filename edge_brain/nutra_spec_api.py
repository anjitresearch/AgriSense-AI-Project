from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.post("/predict/nutra")
def predict_nutra():
    return {"curcumin": "6.1%", "polyphenol": "2.4%"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
