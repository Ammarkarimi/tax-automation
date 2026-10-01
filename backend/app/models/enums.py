"""Enumerations shared by models, schemas, the tax engine and the AI pipeline."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    SUPPORT = "support"  # read-only operational access, no PII
    ADMIN = "admin"


class FilingStatus(StrEnum):
    SINGLE = "single"
    MARRIED_JOINT = "married_joint"
    MARRIED_SEPARATE = "married_separate"
    HEAD_OF_HOUSEHOLD = "head_of_household"


class DocumentType(StrEnum):
    W2 = "w2"
    F1099_NEC = "1099_nec"
    F1099_MISC = "1099_misc"
    F1099_K = "1099_k"
    F1099_INT = "1099_int"
    F1099_DIV = "1099_div"
    INVOICE = "invoice"
    RECEIPT = "receipt"
    BANK_CSV = "bank_csv"
    OTHER = "other"


TAX_FORM_TYPES = {
    DocumentType.W2,
    DocumentType.F1099_NEC,
    DocumentType.F1099_MISC,
    DocumentType.F1099_K,
    DocumentType.F1099_INT,
    DocumentType.F1099_DIV,
}


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class Direction(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class Category(StrEnum):
    """Transaction categories. Each business-expense category maps to a Schedule C line."""

    # --- Income ---
    BUSINESS_INCOME = "business_income"  # Sch C line 1 gross receipts
    OTHER_BUSINESS_INCOME = "other_business_income"  # Sch C line 6
    INTEREST_INCOME = "interest_income"  # Form 1040 line 2b
    TRANSFER = "transfer"  # moving money between own accounts: not income/expense
    LOAN = "loan"  # loan proceeds/principal: not income/expense
    PERSONAL = "personal"  # personal spending or non-business deposits

    # --- Schedule C expenses ---
    ADVERTISING = "advertising"  # line 8
    CAR_TRUCK = "car_truck"  # line 9 (actual costs; mileage handled in profile)
    COMMISSIONS_FEES = "commissions_fees"  # line 10 (platform fees, card processing)
    CONTRACT_LABOR = "contract_labor"  # line 11
    DEPRECIATION = "depreciation"  # line 13 (equipment; section 179)
    EMPLOYEE_BENEFITS = "employee_benefits"  # line 14
    INSURANCE = "insurance"  # line 15 (business insurance, not health)
    INTEREST_MORTGAGE = "interest_mortgage"  # line 16a
    INTEREST_OTHER = "interest_other"  # line 16b (business loan / card interest)
    LEGAL_PROFESSIONAL = "legal_professional"  # line 17
    OFFICE_EXPENSE = "office_expense"  # line 18
    PENSION_PLANS = "pension_plans"  # line 19 (for employees)
    RENT_EQUIPMENT = "rent_equipment"  # line 20a
    RENT_PROPERTY = "rent_property"  # line 20b (shop rent)
    REPAIRS = "repairs"  # line 21
    SUPPLIES = "supplies"  # line 22
    TAXES_LICENSES = "taxes_licenses"  # line 23
    TRAVEL = "travel"  # line 24a
    MEALS = "meals"  # line 24b (50% deductible)
    UTILITIES = "utilities"  # line 25 (incl. business phone/internet)
    WAGES = "wages"  # line 26
    SOFTWARE = "software"  # line 27b other expenses
    BANK_FEES = "bank_fees"  # line 27b
    EDUCATION = "education"  # line 27b
    OTHER_EXPENSE = "other_expense"  # line 27b
    RETURNS_ALLOWANCES = "returns_allowances"  # Sch C line 2 (refunds to customers)
    INVENTORY_PURCHASES = "inventory_purchases"  # Sch C Part III (COGS) line 36

    # --- Non-Schedule C items that still matter ---
    HEALTH_INSURANCE = "health_insurance"  # Schedule 1 line 17 (SE health insurance)
    RETIREMENT_CONTRIBUTION = "retirement_contribution"  # Schedule 1 line 16 (SEP/Solo 401k)
    ESTIMATED_TAX_PAYMENT = "estimated_tax_payment"  # Form 1040 line 26
    UNCATEGORIZED = "uncategorized"


# Schedule C line for each deductible business-expense category.
SCHEDULE_C_LINE: dict[Category, str] = {
    Category.ADVERTISING: "8",
    Category.CAR_TRUCK: "9",
    Category.COMMISSIONS_FEES: "10",
    Category.CONTRACT_LABOR: "11",
    Category.DEPRECIATION: "13",
    Category.EMPLOYEE_BENEFITS: "14",
    Category.INSURANCE: "15",
    Category.INTEREST_MORTGAGE: "16a",
    Category.INTEREST_OTHER: "16b",
    Category.LEGAL_PROFESSIONAL: "17",
    Category.OFFICE_EXPENSE: "18",
    Category.PENSION_PLANS: "19",
    Category.RENT_EQUIPMENT: "20a",
    Category.RENT_PROPERTY: "20b",
    Category.REPAIRS: "21",
    Category.SUPPLIES: "22",
    Category.TAXES_LICENSES: "23",
    Category.TRAVEL: "24a",
    Category.MEALS: "24b",
    Category.UTILITIES: "25",
    Category.WAGES: "26",
    Category.SOFTWARE: "27b",
    Category.BANK_FEES: "27b",
    Category.EDUCATION: "27b",
    Category.OTHER_EXPENSE: "27b",
}

INCOME_CATEGORIES = {
    Category.BUSINESS_INCOME,
    Category.OTHER_BUSINESS_INCOME,
    Category.INTEREST_INCOME,
}

NON_TAX_CATEGORIES = {Category.TRANSFER, Category.LOAN, Category.PERSONAL, Category.UNCATEGORIZED}

CATEGORY_DESCRIPTIONS: dict[Category, str] = {
    Category.BUSINESS_INCOME: "Sales, client payments, platform payouts (gross receipts)",
    Category.OTHER_BUSINESS_INCOME: "Other business income (rebates, prizes related to business)",
    Category.INTEREST_INCOME: "Bank interest",
    Category.TRANSFER: "Transfer between your own accounts (not taxable/deductible)",
    Category.LOAN: "Loan proceeds or principal repayment (not taxable/deductible)",
    Category.PERSONAL: "Personal spending or personal deposits (not business)",
    Category.ADVERTISING: "Ads, marketing, signage, website promotion",
    Category.CAR_TRUCK: "Fuel, parking, tolls, vehicle repairs for business use",
    Category.COMMISSIONS_FEES: "Platform fees, payment-processing / card fees, commissions",
    Category.CONTRACT_LABOR: "Payments to independent contractors",
    Category.DEPRECIATION: "Equipment, machinery, computers (Section 179 / depreciation)",
    Category.EMPLOYEE_BENEFITS: "Employee benefit programs",
    Category.INSURANCE: "Business insurance (liability, property) — not health",
    Category.INTEREST_MORTGAGE: "Mortgage interest on business property",
    Category.INTEREST_OTHER: "Interest on business loans / business credit cards",
    Category.LEGAL_PROFESSIONAL: "Lawyers, accountants, tax software, bookkeeping",
    Category.OFFICE_EXPENSE: "Postage, printer ink, small office items",
    Category.PENSION_PLANS: "Employee pension / profit-sharing plans",
    Category.RENT_EQUIPMENT: "Rented vehicles, machinery, equipment",
    Category.RENT_PROPERTY: "Shop / office / storage rent",
    Category.REPAIRS: "Repairs and maintenance of business property",
    Category.SUPPLIES: "Materials and supplies consumed by the business",
    Category.TAXES_LICENSES: "Business licenses, permits, payroll taxes, sales tax remitted",
    Category.TRAVEL: "Business travel: airfare, lodging, transport",
    Category.MEALS: "Business meals (generally 50% deductible)",
    Category.UTILITIES: "Electricity, water, business phone and internet",
    Category.WAGES: "Wages paid to employees",
    Category.SOFTWARE: "Software, SaaS subscriptions, cloud services",
    Category.BANK_FEES: "Business bank account fees",
    Category.EDUCATION: "Courses and training that maintain/improve business skills",
    Category.OTHER_EXPENSE: "Other ordinary and necessary business expenses",
    Category.RETURNS_ALLOWANCES: "Refunds/returns given to customers",
    Category.INVENTORY_PURCHASES: "Stock bought for resale (cost of goods sold)",
    Category.HEALTH_INSURANCE: "Self-employed health insurance premiums",
    Category.RETIREMENT_CONTRIBUTION: "SEP-IRA / Solo 401(k) contributions",
    Category.ESTIMATED_TAX_PAYMENT: "IRS estimated tax payments (Form 1040-ES)",
    Category.UNCATEGORIZED: "Needs review",
}


class ClassifiedBy(StrEnum):
    AI = "ai"
    RULES = "rules"
    USER = "user"
    IMPORT = "import"
