from typing import Union

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class User(BaseModel):
    username: str
    user_id: int

class Request(BaseModel):
    projname: str
    owner_id: int 
    price: float
    link: str

@app.get("user/{user_id}")
def update_user(username: str, user_id: int):
    return {"username": username, "user_id": user_id}

@app.put("/items/{item_id}")
def update_item(item_id: int, item: Request):
    return {"item_name": item.projname, "item_id": item_id}