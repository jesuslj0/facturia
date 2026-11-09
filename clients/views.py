from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views import View

from django.http import Http404
from clients.forms import ClientProfileForm
from billing_ai.storage import private_file_response


class ClientDetailView(LoginRequiredMixin, View):
    template_name = 'private/clients/client_detail.html'

    def get_client(self):
        return self.request.user.client

    def get(self, request):
        client = self.get_client()
        form = ClientProfileForm(instance=client)
        users = client.users.prefetch_related('roles').all()
        roles = client.roles.all()
        return render(request, self.template_name, {
            'client': client,
            'form': form,
            'users': users,
            'roles': roles,
        })

    def post(self, request):
        client = self.get_client()
        form = ClientProfileForm(request.POST, request.FILES, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil del cliente actualizado correctamente.')
            return redirect('clients:detail')
        users = client.users.prefetch_related('roles').all()
        roles = client.roles.all()
        return render(request, self.template_name, {
            'client': client,
            'form': form,
            'users': users,
            'roles': roles,
        })


class ClientLogoView(LoginRequiredMixin, View):
    """Logo del cliente del usuario autenticado (nunca el de otro tenant)."""

    def get(self, request):
        client = request.user.client
        if not client.logo:
            raise Http404("Sin logo")
        return private_file_response(client.logo)
