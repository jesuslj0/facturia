from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from billing_ai.storage import private_file_response
from clients.forms import ClientInfoForm, ClientProfileForm, UserPasswordForm, UserProfileForm
from documents.models import Document


TABS = ('perfil', 'empresa')


class ClientDetailView(LoginRequiredMixin, View):
    """Cuenta: pestañas «Mi perfil» (datos del usuario) y «Mi empresa» (datos del cliente).

    Tres formularios en la misma página, distinguidos por el campo `form_name`
    (`account`, `password` -> pestaña perfil; `company_info`, `company` -> pestaña empresa; sin él se asume `company`).
    """
    template_name = 'private/clients/client_detail.html'

    def get_client(self):
        return self.request.user.client

    def render_page(self, request, *, tab=None, account_form=None, password_form=None, company_form=None, info_form=None):
        client = self.get_client()
        tab = tab if tab in TABS else (request.GET.get('tab') if request.GET.get('tab') in TABS else 'perfil')
        return render(request, self.template_name, {
            'tab': tab,
            'client': client,
            'form': company_form or ClientProfileForm(instance=client),
            'account_form': account_form or UserProfileForm(instance=request.user),
            'password_form': password_form or UserPasswordForm(request.user),
            'info_form': info_form or ClientInfoForm(instance=client),
            'documents_count': Document.all_objects.filter(client=client, is_current=True).count(),
            'users': client.users.prefetch_related('roles').all(),
            'roles': client.roles.all(),
            'my_roles': request.user.roles.all(),
        })

    @staticmethod
    def back(tab):
        return redirect(f"{reverse('clients:detail')}?tab={tab}")

    def get(self, request):
        return self.render_page(request)

    def post(self, request):
        name = request.POST.get('form_name', 'company')

        if name == 'account':
            form = UserProfileForm(request.POST, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Tus datos se han actualizado.')
                return self.back('perfil')
            return self.render_page(request, tab='perfil', account_form=form)

        if name == 'password':
            form = UserPasswordForm(request.user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)  # no cerrar la sesión actual
                messages.success(request, 'Contraseña cambiada correctamente.')
                return self.back('perfil')
            return self.render_page(request, tab='perfil', password_form=form)

        if name == 'company_info':
            form = ClientInfoForm(request.POST, instance=self.get_client())
            if form.is_valid():
                form.save()
                messages.success(request, 'Información de la empresa actualizada.')
                return self.back('empresa')
            return self.render_page(request, tab='empresa', info_form=form)

        form = ClientProfileForm(request.POST, request.FILES, instance=self.get_client())
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil del cliente actualizado correctamente.')
            return self.back('empresa')
        return self.render_page(request, tab='empresa', company_form=form)


class ClientLogoView(LoginRequiredMixin, View):
    """Logo del cliente del usuario autenticado (nunca el de otro tenant)."""

    def get(self, request):
        client = request.user.client
        if not client.logo:
            raise Http404("Sin logo")
        return private_file_response(client.logo)
