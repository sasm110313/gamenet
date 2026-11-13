from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from apps.applications.services import (
    get_games_catalog,
    add_game,
    update_game,
    delete_game,
    reset_games_catalog,
)
from apps.core.redirects import safe_redirect_next


@login_required
@require_http_methods(["GET", "POST"])
def games_list(request):
    """View and manage games and executables catalog."""
    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "add":
            name = request.POST.get("name", "")
            category = request.POST.get("category", "")
            icon = request.POST.get("icon", "🎮")
            executable = request.POST.get("executable", "")
            arguments = request.POST.get("arguments", "")
            working_dir = request.POST.get("working_dir", "")
            is_active = request.POST.get("is_active") == "on"

            if not name.strip():
                messages.error(request, "نام بازی الزامی است.")
            else:
                add_game(
                    name=name,
                    category=category,
                    icon=icon,
                    executable=executable,
                    arguments=arguments,
                    working_dir=working_dir,
                    is_active=is_active,
                )
                messages.success(request, f"بازی «{name}» با موفقیت افزوده شد.")

        elif action == "edit":
            game_id = request.POST.get("game_id", "")
            name = request.POST.get("name", "")
            category = request.POST.get("category", "")
            icon = request.POST.get("icon", "🎮")
            executable = request.POST.get("executable", "")
            arguments = request.POST.get("arguments", "")
            working_dir = request.POST.get("working_dir", "")
            is_active = request.POST.get("is_active") == "on"

            if not game_id or not name.strip():
                messages.error(request, "شناسه و نام بازی الزامی است.")
            else:
                res = update_game(
                    game_id=game_id,
                    name=name,
                    category=category,
                    icon=icon,
                    executable=executable,
                    arguments=arguments,
                    working_dir=working_dir,
                    is_active=is_active,
                )
                if res:
                    messages.success(request, f"تغییرات بازی «{name}» ذخیره شد.")
                else:
                    messages.error(request, "بازی مورد نظر یافت نشد.")

        elif action == "delete":
            game_id = request.POST.get("game_id", "")
            if delete_game(game_id):
                messages.success(request, "بازی با موفقیت حذف شد.")
            else:
                messages.error(request, "بازی یافت نشد.")

        elif action == "toggle":
            game_id = request.POST.get("game_id", "")
            catalog = get_games_catalog()
            target = next((g for g in catalog if g.get("id") == game_id), None)
            if target:
                new_state = not target.get("is_active", True)
                update_game(
                    game_id=game_id,
                    name=target.get("name", ""),
                    category=target.get("category", ""),
                    icon=target.get("icon", "🎮"),
                    executable=target.get("executable", ""),
                    arguments=target.get("arguments", ""),
                    working_dir=target.get("working_dir", ""),
                    is_active=new_state,
                )
                messages.success(request, f"وضعیت بازی به {'فعال' if new_state else 'غیرفعال'} تغییر یافت.")

        elif action == "reset":
            reset_games_catalog()
            messages.success(request, "لیست بازی‌ها به حالت پیش‌فرض بازنشانی شد.")

        next_url = request.POST.get("next") or request.path
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = request.path
        return redirect(next_url)

    # GET request
    games = get_games_catalog()
    ctx = {
        "games": games,
        "games_total": len(games),
        "games_active": sum(1 for g in games if g.get("is_active", True)),
    }
    return render(request, "games/games_list.html", ctx)


def api_games_catalog(request):
    """API returning active games list for client applications."""
    games = get_games_catalog()
    active_only = request.GET.get("all") != "1"
    if active_only:
        games = [g for g in games if g.get("is_active", True)]
    return JsonResponse({"ok": True, "games": games})
