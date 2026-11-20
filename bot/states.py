"""Aiogram FSM states for Norin AI Hisobot Bot."""

from aiogram.fsm.state import State, StatesGroup


class SaleStates(StatesGroup):
    waiting_sale_input = State()
    waiting_sale_clarify = State()
    waiting_edit_item_weight = State()
    waiting_edit_item_price = State()
    waiting_client_payment_amount = State()
    waiting_edit_payment_amount = State()


class ClientStates(StatesGroup):
    waiting_client_name = State()
    waiting_client_phone = State()
    waiting_client_opening_debt = State()
    waiting_client_custom_price = State()
    waiting_client_group_id = State()
    waiting_client_alias = State()
    waiting_client_edit_name = State()
    waiting_client_edit_phone = State()
    waiting_client_edit_opening_debt = State()


class ProductStates(StatesGroup):
    waiting_product_name = State()
    waiting_product_cost = State()
    waiting_product_sell = State()
    waiting_edit_product_cost = State()
    waiting_edit_product_sell = State()
    waiting_product_alias = State()
    waiting_product_edit_name = State()


class WalletStates(StatesGroup):
    waiting_expense_amount = State()
    waiting_cash_in_amount = State()
    waiting_kassa_debt_amount = State()
    waiting_kassa_repay_amount = State()
    waiting_edit_cash_amount = State()
    waiting_counted_cash = State()
    waiting_report_group_id = State()


class SuperAdminStates(StatesGroup):
    waiting_monthly_price = State()
    waiting_owner_contact = State()
    waiting_tenant_name = State()
    waiting_plan_name = State()
    waiting_grace_days = State()
    waiting_add_user_id = State()
    waiting_add_user_same_tenant_id = State()
    waiting_add_user_name = State()
    waiting_new_tenant_name = State()
    waiting_custom_extend_days = State()
    waiting_broadcast_text = State()
