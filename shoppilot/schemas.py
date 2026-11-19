"""Strict Pydantic domain schemas for ShopPilot tools and structured outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CategoryType = Literal[
    "electronics",
    "audio",
    "gaming",
    "home_kitchen",
    "wearables",
    "toys_gifts",
    "outdoor",
]

SortByType = Literal["price_asc", "price_desc", "discount_desc", "rating_desc", "deal_score_desc"]

BuyRecommendationType = Literal["BUY_NOW", "WAIT", "SET_ALERT", "AVOID_FAKE_DEAL"]


class RetailerOffer(BaseModel):
    """A single retailer's current offer for a product."""

    retailer: str
    current_price: float = Field(ge=0)
    list_price: float = Field(ge=0)
    shipping_cost: float = Field(default=0.0, ge=0)
    in_stock: bool = True
    estimated_delivery_days: int = Field(default=3, ge=1)
    return_window_days: int = Field(default=30, ge=0)
    membership_required: str | None = None
    product_url: str


class PriceHistoryStats(BaseModel):
    """90-day historical pricing telemetry used to detect genuine vs. inflated deals."""

    avg_90d_price: float = Field(ge=0)
    min_90d_price: float = Field(ge=0)
    max_90d_price: float = Field(ge=0)
    all_time_low: float = Field(ge=0)
    last_black_friday_price: float | None = None
    typical_holiday_drop_pct: float = Field(default=15.0, ge=0, le=90)


class CatalogProduct(BaseModel):
    """Canonical product record across multiple retailers."""

    product_id: str
    name: str
    brand: str
    category: CategoryType
    rating: float = Field(ge=0, le=5)
    review_count: int = Field(ge=0)
    tags: list[str] = Field(default_factory=list)
    offers: list[RetailerOffer]
    price_history: PriceHistoryStats


class CouponOffer(BaseModel):
    """Promo code, cashback portal, or credit card reward."""

    code: str | None = None
    source: str
    retailer: str
    discount_type: Literal["percent", "fixed_usd", "cashback_percent"]
    discount_value: float = Field(gt=0)
    min_spend_usd: float = Field(default=0.0, ge=0)
    stackable: bool = True
    membership_required: str | None = None
    expires_on: str
    description: str


class WatchlistItem(BaseModel):
    """A user-tracked product in persistent state."""

    product_id: str
    product_name: str
    recipient: str = "Self"
    target_price_usd: float = Field(gt=0)
    current_best_price_usd: float | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["watching", "target_met", "purchased"] = "watching"


class PriceAlertRule(BaseModel):
    """Structured price-drop alert rule."""

    alert_id: str
    product_id: str
    product_name: str
    target_price_usd: float = Field(gt=0)
    notify_channel: Literal["chat", "email_digest", "push"] = "chat"
    active: bool = True


class ToolResponse(BaseModel):
    """Uniform envelope returned by all ShopPilot tools."""

    status: Literal["success", "error", "not_found"]
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
