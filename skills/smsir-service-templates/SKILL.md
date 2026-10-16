---
name: smsir-service-templates
description: Integrate SMS.ir v1 service-template verification messages and mobile OTP flows, including admin-managed credentials, template parameters, delivery errors and abuse limits. Use for SMS.ir service templates rather than bulk marketing SMS.
---

# SMS.ir service templates

Read the current provider documentation at https://apidocs.sms.ir/ and the official SDK at https://github.com/IPeCompany/SmsPanelV2.DotNet when changing the wire contract. If the documentation website is unavailable, inspect the official SDK's `SmsIr.cs`, `Routes/SendRoutes.cs`, request models and HTTP response helpers; distinguish SDK evidence from a verified live API call.

## Verification contract

- Send `POST https://api.sms.ir/v1/send/verify` with `X-API-KEY` and JSON content type.
- Body: `{"mobile":"09121234567","templateId":123456,"parameters":[{"name":"CODE","value":"123456"}]}`. Use the approved service-template ID and exact parameter name from the customer's SMS.ir account; `CODE` is a configurable default.
- This operation uses a service template. It does not require a bulk sender line. Do not substitute a legacy username/password or bulk endpoint for OTP.
- Treat both HTTP errors and a JSON `status` other than `1` as failure. An HTTP 200 alone does not confirm submission. Submission acceptance does not establish delivery to the handset.
- Use a bounded timeout and disable redirects so the API key is not forwarded to another origin. Do not retry a timeout automatically: delivery may already have been accepted.

## Application integration

- Normalize Persian/Arabic digits and Iranian country-code variants to a canonical mobile number before storage, lookup and rate limiting.
- Keep credentials server-side and encrypted at rest. Expose only configured flags and masked hints to admin; never return the key or OTP to a public API or production logs.
- Make the approved template ID, parameter name and provider configuration accessible in admin settings. Test messages require an explicit recipient and send action.
- Store only a hash of the OTP, with expiry and a bounded attempt count. Commit failed-attempt increments even when returning an error. Resends invalidate earlier challenges.
- On verification, issue a short-lived, single-use completion grant; serialize account creation by canonical mobile so concurrent requests cannot create duplicate demos or introductory credit.
- Mobile identities can exist in several tenants. After verification, offer an organization choice instead of silently selecting a tenant. Preserve an existing user's second factor.

## SedaSanj ownership

For this repository, the shared provider client is `sedasanj/apps/api/app/services/smsir.py`; admin settings are managed by `demo_settings.py`, and phone authentication is in `routers/phone_auth.py`. Keep the existing signup flow on this same client so the admin configuration applies to both entry points.

Verify the JSON contract and provider error handling with a mock HTTP transport; use an isolated database to check one-time grants, persisted failed attempts and duplicate signup protection. Real SMS tests incur provider charges and must use the user's explicit send action.
