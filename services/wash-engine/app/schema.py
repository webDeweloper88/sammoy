from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class AccountUpdateRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    login: str | None = Field(default=None, min_length=1, max_length=80)
    new_password: str | None = Field(default=None, min_length=8, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


class UserResponse(BaseModel):
    id: int
    login: str
    role: str
    display_name: str
    must_change_password: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: UserResponse


class KioskSettingsRequest(BaseModel):
    config: dict


class WashModeRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=40)


class WashCreditRequest(BaseModel):
    amount_sum: int = Field(gt=0, le=10_000_000)
    source: str = Field(default="manual", min_length=1, max_length=80)


class WashParametersRequest(BaseModel):
    parameters: dict


class VipProfileRequest(BaseModel):
    id: int | None = Field(default=None,ge=1)
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    grant_seconds: int = Field(ge=0, le=24 * 60 * 60)
    max_uses_per_day: int | None = Field(default=None, ge=1, le=1000)
    owner_notes: str = Field(default="", max_length=500)


class VipProfilesRequest(BaseModel):
    profiles: list[VipProfileRequest]


class RfidCardRequest(BaseModel):
    uid: str = Field(min_length=1, max_length=80)
    card_type: str = Field(default="vip", pattern="^vip$")
    status: str = Field(default="active", pattern="^(active|blocked|lost|expired)$")
    enabled: bool = True
    display_name: str = Field(default="", max_length=120)
    vip_profile_id: int | None = None
    expires_at: str | None = Field(default=None,max_length=80)


class WashSimTotalStopRequest(BaseModel):
    active: bool | None = None


class WashSimPulsesRequest(BaseModel):
    count: int = Field(gt=0, le=1000)


class WashSimRfidRequest(BaseModel):
    uid: str = Field(min_length=4, max_length=80, pattern=r"^[0-9A-Fa-f]+$")


class WashSimLicenseRequest(BaseModel):
    mode: str = Field(pattern="^(real|valid|expired|disabled|sync_failed)$")


class ClickIntentRequest(BaseModel):
    amount_sum: int = Field(ge=1, le=10_000_000)


class ClickSettingsRequest(BaseModel):
    enabled: bool = False
    gateway_url: str = Field(default="", max_length=300)
    site_code: str = Field(default="", max_length=80)
    site_token: str = Field(default="", max_length=300)
    post_no: int = Field(default=1, ge=1, le=100)
    min_amount_sum: int = Field(default=1000, ge=1, le=10_000_000)
    max_amount_sum: int = Field(default=10_000_000, ge=1, le=100_000_000)


class LicenseSettingsRequest(BaseModel):
    enabled: bool = False
    gateway_url: str = Field(default="", max_length=300)
    site_code: str = Field(default="", max_length=80)
    site_token: str = Field(default="", max_length=300)
    post_no: int = Field(default=1, ge=1, le=100)
    sync_interval_seconds: int = Field(default=43_200, ge=300, le=86_400)
    grace_seconds: int = Field(default=604_800, ge=0, le=30 * 24 * 60 * 60)


class InstallApplyRequest(BaseModel):
    site_code: str = Field(default="", min_length=1, max_length=80)
    post_no: int = Field(default=1, ge=1, le=100)
    gateway_url: str = Field(default="https://gateway.example.com", max_length=300)
    site_token: str = Field(default="", max_length=300)
    license_enabled: bool = True
    click_enabled: bool = False
    click_min_amount_sum: int = Field(default=1000, ge=1, le=10_000_000)
    click_max_amount_sum: int = Field(default=10_000_000, ge=1, le=100_000_000)
    sync_interval_seconds: int = Field(default=7200, ge=300, le=86_400)
    grace_seconds: int = Field(default=604_800, ge=0, le=30 * 24 * 60 * 60)
    reset_runtime_data: bool = False
    reset_confirmation: str = Field(default="", max_length=20)


class OfflineLicenseCodeRequest(BaseModel):
    code: str = Field(min_length=20, max_length=1200)


class CommissioningClaimRequest(BaseModel):
    gateway_url: str = Field(default="https://gateway.example.com", min_length=8, max_length=300)
    activation_code: str = Field(min_length=8, max_length=32)
    click_enabled: bool = False


class CommissioningOfflineRequest(BaseModel):
    site_code: str = Field(min_length=1, max_length=80)
    post_no: int = Field(ge=1, le=1000)
    gateway_url: str = Field(default="https://gateway.example.com", min_length=8, max_length=300)
    purpose: str = Field(default="activate", pattern="^(activate|replace_microsd)$")
    click_enabled: bool = False


class CommissioningCompleteRequest(BaseModel):
    confirmation: str = Field(pattern="^READY$")


from pydantic import ConfigDict
class CustomerRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    uid:str=Field(pattern=r'^[0-9A-Fa-f]{4,64}$')
    display_name:str=Field(default='',max_length=120)
    enabled:bool=True
    status:str=Field(default='active',pattern=r'^(active|blocked|lost|expired)$')
    expected_revision:int=Field(ge=0)
