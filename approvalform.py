from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Request(BaseModel):
    projname: str
    owner_id: int 
    price: float
    link: str

items = []
next_id = 1

@app.post("/items")
def create_item(item: Request):
    global next_id
    item_record = {
        "item_id": next_id,
        **item.dict()
    }
    items.append(item_record)
    next_id += 1
    return item_record

@app.get("/items")
def list_items():
    return items

@app.get("/items/by-owner/{owner_id}")
def items_for_user(owner_id: int):
    return [i for i in items if i["owner_id"] == owner_id]
