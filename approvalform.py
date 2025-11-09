from typing import Union

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Request(BaseModel):
    projname: str
    price: float
    link: str

@app.put("/items/{item_id}")
def update_item(item_id: int, item: Request):
    return {"item_name": item.projname, "item_id": item_id}