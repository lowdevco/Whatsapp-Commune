from .models import WhatsAppAccount

def account_list(request):
    if request.user.is_authenticated:
        seen_numbers = set()
        unique_accounts = []
        for account in WhatsAppAccount.objects.filter(user=request.user):
            if account.number not in seen_numbers:
                unique_accounts.append(account)
                seen_numbers.add(account.number)
        accounts = unique_accounts
    else:
        accounts = []
    return {'accounts': accounts}
