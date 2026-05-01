from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime
from typing import Optional
from enum import Enum


class Category(str, Enum):
    CLOTHES = "Clothes"
    FUEL = "Fuel"
    ENTERTAINMENT = "Entertainment"
    EDUCATION = "Education"
    UBER = "Uber"
    GROCERIES = "Groceries"
    EATING_OUT = "Eating out"
    BEAUTY = "Beauty"
    HEALTHCARE = "Healthcare"
    GIFTS = "Gifts"
    TRANSPORT = "Transport"
    CAR = "Car"
    HOLIDAYS = "Holidays"
    HOBBIES = "Hobbies"
    MISCELLANEOUS = "Miscellaneous"
    SUBSCRIPTIONS = "Subscriptions"
    UTILITIES = "Utilities"
    CARRYOVER = "CarryOver"
    AJUSTE = "Ajuste de Reconciliação"


class Expense(BaseModel):
    date: Optional[datetime] = None
    description: str
    category: Category
    amount: float
    subscription: bool = False
    notes: str = ""

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return round(v, 2)

    @model_validator(mode="after")
    def set_date_now(self):
        if self.date is None:
            self.date = datetime.now()
        return self

    def to_row(self) -> list:
        return [
            self.date.strftime("%d/%m/%Y"),
            self.description,
            self.category.value,
            self.amount,
            self.subscription,
            self.notes,
        ]