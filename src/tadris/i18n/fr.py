# All user-facing strings. Import as `from tadris.i18n.fr import t`.

t = {
    "app.name": "Tadris",
    "auth.invalid": "Identifiant ou mot de passe incorrect.",
    "auth.disabled": "Ce compte est désactivé.",
    "auth.username_taken": "Ce nom d'utilisateur existe déjà.",
    "auth.username_required": "Le nom d'utilisateur est obligatoire.",
    "auth.password_short": "Le mot de passe doit contenir au moins 8 caractères.",
    "auth.password_mismatch": "Les mots de passe ne correspondent pas.",
    "auth.wrong_current_password": "Le mot de passe actuel est incorrect.",
    "auth.already_initialized": "L'application a déjà un compte directeur.",
    "auth.school_name_required": "Le nom de l'école est obligatoire.",
    "permission.denied": "Vous n'avez pas le droit d'effectuer cette action.",
    "not_found": "Élément introuvable.",
    "validation.generic": "Donnée invalide.",
    "money.invalid": "Montant invalide.",
    "settings.unknown_key": "Paramètre inconnu.",
    "date.invalid": "Date invalide. Format attendu : jj/mm/aaaa, par exemple 18/10/2026.",
    "phone.invalid": (
        "Numéro de téléphone invalide. Exemple : 0661 90 25 47 (mobile) ou 048 55 12 30 (fixe)."
    ),
    "student.not_found": "Élève introuvable.",
    "student.last_name_required": "Le nom de l'élève est obligatoire.",
    "student.first_name_required": "Le prénom de l'élève est obligatoire.",
    "student.birth_date_future": "La date de naissance ne peut pas être dans le futur.",
    "student.already_inactive": "Cet élève est déjà désactivé.",
    "student.already_active": "Cet élève est déjà actif.",
    "student.has_live_enrollments": (
        "Cet élève est encore inscrit dans un groupe. Retirez-le d'abord de ses groupes."
    ),
    "registration.not_found": "Inscription annuelle introuvable.",
    "registration.no_open_year": (
        "Aucune année scolaire n'est ouverte. Ouvrez une année dans Paramètres."
    ),
    "registration.student_inactive": "Cet élève est désactivé. Réactivez-le d'abord.",
    "registration.exists": (
        "Cet élève a déjà son inscription annuelle {label} ({level}). Pour l'ajouter à un autre "
        "groupe, utilisez « Inscrire dans un groupe »."
    ),
    "registration.fee_invalid": "Le montant des frais d'inscription est invalide.",
    "registration.fee_description": "Frais d'inscription {label}",
    "registration.cancelled": "Cette inscription annuelle est annulée.",
    "registration.already_cancelled": "Cette inscription annuelle est déjà annulée.",
    "registration.year_closed": "L'année {label} est clôturée : l'inscription ne peut plus changer.",
    "registration.same_level": "L'élève est déjà inscrit dans ce niveau.",
    "registration.has_live_enrollments": (
        "L'élève est encore dans {count} groupe(s) de cette année. Retirez-le d'abord de ses "
        "groupes."
    ),
    "registration.fee_paid": (
        "Des frais d'inscription ont déjà été payés ({amount}). Remboursez-les avant d'annuler."
    ),
    "registration.level_required": "Choisissez le niveau.",
    "registration.reason_required": "Indiquez le motif de l'annulation.",
    "enrollment.not_found": "Inscription dans le groupe introuvable.",
    "enrollment.not_registered": (
        "Cet élève n'a pas d'inscription annuelle pour l'année {label}. Inscrivez-le d'abord "
        "pour l'année, puis dans ses groupes."
    ),
    "enrollment.group_other_year": "Ce groupe n'est pas de l'année ouverte ({label}).",
    "enrollment.already_in": "Cet élève est déjà dans le groupe {group}.",
    "enrollment.trial_used": "Cet élève a déjà eu son essai gratuit : un seul essai par élève.",
    "enrollment.full": "Le groupe {group} est complet (places : {seats}).",
    "enrollment.room_full": (
        "Le groupe {group} est complet : la salle {room} limite le groupe (places : {seats})."
    ),
    "enrollment.date_outside": (
        "La date d'entrée doit être entre le {start} (début du groupe) et le {end} (fin de "
        "l'année)."
    ),
    "enrollment.level_mismatch": (
        "Le groupe {group} est de niveau {group_level}, l'élève est inscrit en {level}. Un élève "
        "ne suit que des groupes de son niveau. Pour changer de niveau, retirez-le de ses groupes "
        "puis utilisez « Changer le niveau » (onglet Inscription)."
    ),
    "enrollment.time_clash": (
        "Conflit d'horaire : {group} a cours le {day} de {start} à {end}, et l'élève est déjà en "
        "{other} de {other_start} à {other_end}."
    ),
    "enrollment.same_subject": (
        "L'élève est déjà en {subject} {level} dans le groupe {other}. Pour le déplacer, utilisez "
        "« Changer de groupe ». Seul le directeur peut l'inscrire dans deux groupes de la même "
        "matière, avec un motif."
    ),
    "enrollment.override_reason_required": "Indiquez le motif de la dérogation.",
    "enrollment.not_live": "Cet élève n'est plus dans ce groupe.",
    "enrollment.not_trial": "Cette inscription n'est pas un essai.",
    "enrollment.same_group": "Choisissez un autre groupe que le groupe actuel.",
    "enrollment.leave_future": "La date de sortie ne peut pas être dans le futur.",
    "enrollment.leave_before_entry": (
        "La date de sortie ne peut pas être avant la date d'entrée ({date})."
    ),
    "enrollment.leave_before_attendance": (
        "Une présence est déjà notée le {date} : la date de sortie ne peut pas être avant."
    ),
    "subscription.not_found": "Abonnement introuvable.",
    "subscription.charge_description": "Abonnement {group} du {start} au {end}",
    "subscription.enrollment_not_live": (
        "L'élève n'est plus dans ce groupe : son abonnement ne peut pas être renouvelé."
    ),
    "subscription.trial": "Un élève en essai n'a pas d'abonnement : confirmez d'abord l'essai.",
    "subscription.group_closed": "Ce groupe est clôturé : pas de nouvel abonnement.",
    "subscription.cancelled": "Cet abonnement est annulé.",
    "subscription.not_latest": (
        "Seul le dernier abonnement peut être renouvelé (celui qui se termine le {end})."
    ),
    "subscription.start_before_end": (
        "Le renouvellement ne peut pas commencer avant la fin de l'abonnement précédent ({end})."
    ),
    "subscription.start_outside_year": (
        "Un abonnement doit commencer pendant l'année scolaire (jusqu'au {end})."
    ),
    "subscription.start_before_entry": (
        "Un abonnement ne peut pas commencer avant l'entrée dans le groupe ({date})."
    ),
    "subscription.already_running": (
        "Cet élève a déjà un abonnement en cours ou à venir dans ce groupe (jusqu'au {end}). "
        "Utilisez « Renouveler »."
    ),
    "subscription.already_cancelled": "Cet abonnement est déjà annulé.",
    "subscription.paid": (
        "Cet abonnement a déjà été payé en partie ({amount}). Remboursez d'abord le paiement."
    ),
    "subscription.in_payout": "Cet abonnement est déjà compté dans un paiement enseignant.",
    "subscription.reason_required": "Indiquez le motif de l'annulation.",
    "payment.not_found": "Paiement introuvable.",
    "payment.amount_invalid": "Le montant doit être un nombre entier de dinars supérieur à 0.",
    "payment.method_invalid": "Mode de paiement invalide.",
    "payment.payer_unknown": "Ce payeur n'est pas un contact de l'élève.",
    "payment.charge_unknown": "Cette ligne n'est pas due par l'élève (ou figure deux fois).",
    "payment.allocation_too_high": (
        "Le montant affecté dépasse ce qui reste à payer sur cette ligne ({amount})."
    ),
    "payment.allocations_exceed": "Les montants affectés dépassent le paiement ({amount}).",
    "payment.reason_required": "Indiquez le motif de l'annulation.",
    "payment.already_voided": "Ce paiement est déjà annulé.",
    "payout_status.draft": "Brouillon",
    "payout_status.approved": "Approuvé",
    "payout_status.paid": "Payé",
    "payout_stamp.draft": "BROUILLON",
    "payout_stamp.approved": "APPROUVÉ",
    "payout_stamp.paid": "PAYÉ",
    "payout_slip.title": "Paiement enseignant",
    "payout_slip.teacher": "Enseignant",
    "payout_slip.period": "Période",
    "payout_slip.period_value": "Mois commencés du {start} au {end}",
    "payout_slip.status": "Statut",
    "payout_slip.approved": "Approuvé",
    "payout_slip.by_on": "par {user} le {date}",
    "payout_slip.paid": "Versé",
    "payout_slip.paid_value": "le {date}, en {method}, par {user}",
    "payout_slip.col.group": "Groupe",
    "payout_slip.col.students": "Élèves",
    "payout_slip.col.months": "Mois",
    "payout_slip.col.revenue": "Recettes",
    "payout_slip.col.rate": "Taux",
    "payout_slip.col.amount": "Montant",
    "payout_slip.col.student": "Élève",
    "payout_slip.col.from": "Début",
    "payout_slip.col.price": "Prix",
    "payout_slip.col.share": "Part",
    "payout_slip.total": "Total à verser",
    "payout_slip.detail": "Détail par élève",
    "payout_slip.note": (
        "Part de l'enseignant : son taux du premier jour de chaque mois, appliqué au prix "
        "complet du mois, payé ou non par l'élève. Chaque ligne est arrondie au dinar "
        "inférieur."
    ),
    "payout_slip.signature": "Signature de l'enseignant",
    "payout.not_found": "Paiement enseignant introuvable.",
    "payouts.caption": (
        "Chaque enseignant reçoit son taux du prix complet de chaque mois de ses groupes, payé "
        "ou non par l'élève. Un paiement prend tous les mois pas encore payés jusqu'à la date "
        "choisie, même un mois renouvelé en retard."
    ),
    "payouts.until": "Payer jusqu'au",
    "payouts.run": "Préparer les brouillons",
    "payouts.run_done": "{count} brouillon(s) préparé(s)",
    "payouts.due_title": "À préparer",
    "payouts.due_empty": "Aucun mois à payer jusqu'à cette date.",
    "payouts.has_draft": "Brouillon à refaire",
    "payouts.prepare": "Préparer le brouillon",
    "payouts.prepared": "Brouillon préparé pour {teacher}",
    "payouts.list_title": "Paiements",
    "payouts.filter.open": "À traiter",
    "payouts.filter.paid": "Payés",
    "payouts.filter.all": "Tous",
    "payouts.empty": "Aucun paiement enseignant.",
    "payouts.period": "du {start} au {end}",
    "payouts.rebuild": "Recalculer",
    "payouts.rebuilt": "Brouillon recalculé : {teacher}, {amount}",
    "payouts.delete": "Supprimer le brouillon",
    "payouts.deleted": "Brouillon de {teacher} supprimé",
    "payouts.confirm_delete_title": "Supprimer le brouillon",
    "payouts.confirm_delete": (
        "Supprimer le brouillon de {teacher} ({period}) ? Ses mois restent à payer."
    ),
    "payouts.approve": "Approuver",
    "payouts.approved": "Paiement de {teacher} approuvé et verrouillé",
    "payouts.confirm_approve_title": "Approuver le paiement",
    "payouts.confirm_approve": (
        "Approuver {amount} pour {teacher} ({period}) ? Le paiement sera verrouillé : il ne "
        "pourra plus être modifié."
    ),
    "payouts.stale": (
        "{count} mois ont été saisis depuis ce brouillon : recalculez-le pour les compter "
        "(sinon ils iront dans le prochain paiement)."
    ),
    "payouts.pay": "Payer",
    "payouts.paid": "Paiement {number} : {teacher}, {amount} versés",
    "payouts.print": "Imprimer",
    "payouts.back": "← Paiements enseignants",
    "payouts.detail_title": "{teacher} · {amount}",
    "payouts.detail_period": "Mois commencés {period} · {months} mois · recettes {revenue}",
    "payouts.tab.groups": "Groupes",
    "payouts.tab.months": "Détail par élève",
    "payouts.col.teacher": "Enseignant",
    "payouts.col.period": "Période",
    "payouts.col.months": "Mois",
    "payouts.col.revenue": "Recettes",
    "payouts.col.amount": "Montant",
    "payouts.col.status": "Statut",
    "payouts.col.number": "N°",
    "payouts.col.draft": "Brouillon",
    "payouts.col.group": "Groupe",
    "payouts.col.students": "Élèves",
    "payouts.col.rate": "Taux",
    "payouts.col.student": "Élève",
    "payouts.col.number_student": "N°",
    "payouts.col.from": "Début",
    "payouts.col.price": "Prix",
    "payouts.col.share": "Part",
    "pay_payout.title": "Payer l'enseignant",
    "pay_payout.submit": "Verser {amount}",
    "pay_payout.method": "Payé en",
    "pay_payout.caption": (
        "Verser {amount} à {teacher} pour les mois commencés {period}. Le bon s'imprime pour "
        "être signé par l'enseignant."
    ),
    "payout.until_too_late": (
        "On paie au plus tard jusqu'à la fin du mois en cours ({date})."
    ),
    "payout.nothing": "Rien à payer à {teacher} jusqu'au {date} : aucun mois non payé.",
    "payout.no_rate": (
        "{teacher} n'a pas de taux le {date}. Ajoutez son taux dans la page Enseignants, puis "
        "recommencez."
    ),
    "payout.zero": "Le taux de {teacher} est de 0 % : il n'y a rien à lui verser.",
    "payout.same_period": (
        "Un paiement couvre déjà exactement la période du {start} au {end}. Choisissez une "
        "autre date de fin (par exemple aujourd'hui)."
    ),
    "payout.not_draft": "Ce paiement enseignant n'est plus un brouillon : il est verrouillé.",
    "payout.not_approved": "Ce paiement enseignant doit d'abord être approuvé.",
    "refund.not_found": "Remboursement introuvable.",
    "refund.charge_not_found": "Ligne à rembourser introuvable.",
    "refund.amount_invalid": "Le montant doit être un nombre entier de dinars supérieur à 0.",
    "refund.reason_required": "Indiquez le motif (ex. : départ de l'élève, erreur de paiement).",
    "refund.exceeds": (
        "Le remboursement dépasse ce qui a été payé sur cette ligne et n'est ni remboursé ni "
        "déjà demandé ({amount})."
    ),
    "refund.not_pending": "Ce remboursement a déjà été décidé.",
    "refund.not_approved": "Ce remboursement doit d'abord être approuvé par la direction.",
    "refund.closed": "Ce remboursement est déjà versé ou refusé.",
    "refund.money_gone": (
        "Un paiement de cette ligne a été annulé depuis l'approbation : seuls {amount} peuvent "
        "être rendus. Refusez ce remboursement et faites une nouvelle demande."
    ),
    "debt.warning": (
        "Attention : cet élève doit déjà {amount} en retard (seuil d'alerte : {threshold})."
    ),
    "holiday.not_found": "Période de vacances introuvable.",
    "holiday.label_required": "Le libellé est obligatoire (ex. : Vacances d'hiver).",
    "holiday.dates_order": "La date de fin doit être le même jour ou après la date de début.",
    "holiday.overlap": "Ces dates chevauchent « {label} » ({start} → {end}).",
    "session.not_found": "Séance introuvable.",
    "session.reason_required": "Indiquez le motif de l'annulation.",
    "session.already_cancelled": "Cette séance est déjà annulée.",
    "session.not_cancelled": "Cette séance n'est pas annulée.",
    "session.cancelled": "Cette séance est annulée.",
    "session.held": "Cette séance a déjà eu lieu (présences notées) : elle ne peut pas être annulée.",
    "session.has_makeup": (
        "Une séance de rattrapage est déjà prévue pour cette séance. Annulez d'abord le rattrapage."
    ),
    "session.group_closed_reason": "Groupe clôturé",
    "session.makeup_needs_cancel": "Seule une séance annulée peut être rattrapée.",
    "session.makeup_outside": (
        "Le rattrapage doit avoir lieu entre le {start} (début du groupe) et le {end} (fin de "
        "l'année)."
    ),
    "attendance.status_invalid": "Statut de présence invalide.",
    "attendance.session_cancelled": "Cette séance est annulée : pas de présences à noter.",
    "attendance.future": (
        "Cette séance est prévue le {date} : les présences se notent à partir de ce jour-là."
    ),
    "attendance.not_in_session": (
        "Un de ces élèves n'est pas dans le groupe à la date de la séance."
    ),
    "print.done": "Document enregistré et ouvert : {name}",
    "print.failed": "Le document n'a pas pu être enregistré.",
    "print.footer": "Imprimé le {date} à {time} par {user}",
    "print.session_title": "Feuille de présence",
    "print.session_when": "{day} {date}, de {start} à {end}",
    "print.session_where": "Salle : {room} · Enseignant : {teacher}",
    "print.session_cancelled": "Séance annulée : {reason}",
    "print.not_renewed_short": "Non renouvelé",
    "print.col.number": "N°",
    "print.col.student": "Élève",
    "print.col.note": "Remarque",
    "print.col.observation": "Observation",
    "print.week_title": "Feuille de présence de la semaine",
    "print.week_when": "Semaine du {first} au {last}",
    "print.week_teacher": "Enseignant : {teacher}",
    "print.week_legend": (
        "P : présent · R : en retard · A : absent · E : excusé · — : pas encore ou plus dans le "
        "groupe ce jour-là. Une case vide est à remplir."
    ),
    "print.week_empty": "Aucune séance ou aucun élève pour ce groupe cette semaine.",
    "receipt.not_found": "Reçu introuvable.",
    "receipt.title": "Reçu de paiement",
    "receipt.duplicate": "DUPLICATA",
    "receipt.date": "Date",
    "receipt.student": "Élève",
    "receipt.student_value": "{name} (N° {number})",
    "receipt.payer": "Payé par",
    "receipt.method": "Mode de paiement",
    "receipt.cashier": "Reçu par",
    "receipt.col.item": "Désignation",
    "receipt.col.amount": "Montant",
    "receipt.credit_line": "Avance (crédit pour les prochains mois)",
    "receipt.total": "Total payé",
    "receipt.left": "Reste à payer au {date}",
    "receipt.credit": "Crédit disponible",
    "receipt.voided": "Reçu annulé le {date} : {reason}",
    "receipt.stamp_paid": "PAYÉ",
    "receipt.stamp_voided": "ANNULÉ",
    "receipt.thanks": "Merci. Conservez ce reçu.",
    "receipt.signature": "Cachet et signature",
    "refund_slip.title": "Bon de remboursement",
    "refund_slip.method": "Rendu en",
    "refund_slip.reason": "Motif",
    "refund_slip.approved_by": "Approuvé par",
    "refund_slip.paid_out_by": "Remis par",
    "refund_slip.total": "Total remboursé",
    "refund_slip.stamp": "REMBOURSÉ",
    "refund_slip.thanks": "Le bénéficiaire reconnaît avoir reçu la somme ci-dessus.",
    "refund_slip.signature": "Signature du bénéficiaire",
    "refund.not_paid_yet": "Le bon s'imprime une fois le remboursement versé.",
    "payment_method.cash": "Espèces",
    "payment_method.transfer": "Virement",
    "payment_method.cheque": "Chèque",
    "payment_method.other": "Autre",
    "percent.invalid": "Pourcentage invalide. Exemple : 60 ou 62,5 (entre 0 et 100).",
    "time.invalid": "Heure invalide. Exemple : 17:30 ou 17h30.",
    "name.required": "Le nom est obligatoire.",
    "name.taken": "Ce nom existe déjà.",
    "year.label_required": "Le libellé de l'année est obligatoire.",
    "year.label_taken": "Une année porte déjà ce libellé.",
    "year.dates_order": "La date de fin doit être après la date de début.",
    "year.overlap": "Ces dates chevauchent l'année {label}.",
    "year.not_found": "Année scolaire introuvable.",
    "year.already_open": "Cette année est déjà ouverte.",
    "year.other_open": "L'année {label} est encore ouverte. Clôturez-la d'abord.",
    "year.not_open": "Cette année n'est pas ouverte.",
    "year.ended": "Cette année est terminée : elle ne peut plus être ouverte.",
    "year.groups_outside": "Des groupes de cette année commencent hors de ces dates.",
    "year.not_usable": (
        "Cette année est clôturée. Choisissez l'année ouverte ou une année à venir."
    ),
    "level.not_found": "Niveau introuvable.",
    "subject.not_found": "Matière introuvable.",
    "level.inactive": "Ce niveau est désactivé.",
    "subject.inactive": "Cette matière est désactivée.",
    "room.not_found": "Salle introuvable.",
    "room.capacity_invalid": "La capacité doit être au moins 1.",
    "room.inactive": "Cette salle est désactivée.",
    "room.in_use": (
        "Cette salle a encore des créneaux en cours ou à venir. Déplacez-les d'abord."
    ),
    "room.too_small": (
        "La salle {room} a {room_capacity} places, mais le groupe compte déjà {enrolled} "
        "élèves inscrits. Choisissez une salle plus grande."
    ),
    "teacher.not_found": "Enseignant introuvable.",
    "teacher.name_required": "Le nom de l'enseignant est obligatoire.",
    "teacher.inactive": "Cet enseignant est désactivé.",
    "teacher.already_inactive": "Cet enseignant est déjà désactivé.",
    "teacher.already_active": "Cet enseignant est déjà actif.",
    "teacher.has_groups": (
        "Cet enseignant a encore des groupes ouverts. Changez d'abord leur enseignant."
    ),
    "rate.before_current": (
        "Le nouveau taux doit commencer après le {date} (début du taux actuel)."
    ),
    "rate.locked": (
        "Ce taux a déjà servi à un paiement enseignant validé. Choisissez une date plus récente."
    ),
    "group.not_found": "Groupe introuvable.",
    "group.name_taken": "Un groupe porte déjà ce nom cette année.",
    "group.price_invalid": "Le prix ne peut pas être négatif.",
    "group.capacity_invalid": "La capacité doit être au moins 1.",
    "group.start_outside_year": "La date de début doit être dans l'année {label}.",
    "group.closed": "Ce groupe est clôturé.",
    "group.already_closed": "Ce groupe est déjà clôturé.",
    "group.not_closed": "Ce groupe n'est pas clôturé.",
    "group.has_enrollments": (
        "Le groupe a déjà des élèves : le niveau, la matière et la date de début "
        "ne peuvent plus changer."
    ),
    "group.same_teacher": "Cet enseignant est déjà celui du groupe.",
    "group.teacher_before_current": (
        "Le changement doit commencer après le {date} (début de l'enseignant actuel)."
    ),
    "group.teacher_date_outside": (
        "La date du changement doit être entre le début du groupe ({start}) "
        "et la fin de l'année ({end})."
    ),
    "group.start_after_teacher_change": (
        "Le groupe change d'enseignant le {date} : il doit commencer avant cette date."
    ),
    "group.slots_have_sessions": (
        "Des séances ont déjà eu lieu : la date de début ne peut plus reculer."
    ),
    "group.teacher_locked": (
        "Cet enseignant a déjà été payé pour ce groupe. Choisissez une date plus récente."
    ),
    "weekday.1": "lundi",
    "weekday.2": "mardi",
    "weekday.3": "mercredi",
    "weekday.4": "jeudi",
    "weekday.5": "vendredi",
    "weekday.6": "samedi",
    "weekday.7": "dimanche",
    "slot.not_found": "Créneau introuvable.",
    "slot.times_order": "L'heure de fin doit être après l'heure de début.",
    "slot.weekday_invalid": "Jour invalide.",
    "slot.room_busy": (
        "La salle {room} est déjà occupée le {day} de {start} à {end} par {group}. "
        "Choisissez une autre salle ou un autre horaire."
    ),
    "slot.group_busy": (
        "Le groupe {group} a déjà cours le {day} de {start} à {end}. Choisissez un autre horaire."
    ),
    "slot.teacher_busy": (
        "{teacher} enseigne déjà le {day} de {start} à {end} ({group}). "
        "Choisissez un autre horaire."
    ),
    "slot.student_busy": (
        "{student}, élève de ce groupe, a déjà cours le {day} de {start} à {end} ({group}). "
        "Choisissez un autre horaire."
    ),
    "slot.students_busy": (
        "{student} et {others} autre(s) élève(s) de ce groupe ont déjà cours le {day} de {start} "
        "à {end} ({group}). Choisissez un autre horaire."
    ),
    "slot.ended": "Ce créneau est déjà terminé.",
    "slot.outside_hours": (
        "Ce créneau sort des horaires de l'école ({opens} – {closes}). Changez l'horaire, "
        "ou les horaires de l'école dans Paramètres, onglet École."
    ),
    "hours.order": "L'heure de fermeture doit être après l'heure d'ouverture.",
    "hours.slots_outside": (
        "{count} créneau(x) sortent de ces horaires, par exemple {group} le {day} de {start} "
        "à {end}. Déplacez-les d'abord dans l'emploi du temps."
    ),
    "contact.name_required": "Le nom du contact est obligatoire.",
    "contact.phone_required": "Le téléphone du contact est obligatoire.",
    "contact.not_linked": "Ce contact n'est pas lié à cet élève.",
    "contact.already_linked": "Ce contact est déjà lié à cet élève.",
    "contact.main_required_first": (
        "C'est le contact principal. Désignez d'abord un autre contact principal."
    ),
    "db.holiday_overlap": "Ces dates chevauchent une autre période de vacances.",
    "db.integrity": "Cette opération enfreint une règle de l'école.",
    "db.payments_immutable": "Les paiements ne peuvent pas être modifiés.",
    "db.allocations_immutable": "Les affectations de paiement ne peuvent pas être modifiées.",
    "db.receipts_immutable": "Les reçus ne peuvent pas être modifiés.",
    "db.voids_immutable": "Les annulations de paiement ne peuvent pas être modifiées.",
    "db.audit_immutable": "Le journal d'audit ne peut pas être modifié.",
    "db.refund_locked": "Ce remboursement est verrouillé.",
    "db.payment_voided": "Ce paiement a été annulé.",
    "db.charge_cancelled": "Cette charge est annulée.",
    "db.different_students": "Le paiement et la charge ne concernent pas le même élève.",
    "db.alloc_exceed_payment": "Les affectations dépassent le montant du paiement.",
    "db.alloc_exceed_charge": "Les affectations dépassent le montant de la charge.",
    "db.void_after_payout": "Ce paiement a déjà été compté dans un paiement enseignant.",
    "db.void_has_refunds": "Ce paiement a déjà des remboursements.",
    "db.charge_locked": "Seuls le statut et la date d'imputation d'une charge peuvent changer.",
    "db.charge_in_payout": "Cette charge a déjà été comptée dans un paiement enseignant.",
    "db.enrollment_other_student": "L'inscription appartient à un autre élève.",
    "db.registration_cancelled": "L'inscription annuelle est annulée.",
    "db.year_mismatch": "L'année scolaire de l'inscription et du groupe diffèrent.",
    "db.level_mismatch": "Le niveau de l'inscription et du groupe diffèrent.",
    "db.group_closed": "Ce groupe est clôturé.",
    "db.group_started": "Le groupe a déjà commencé.",
    "db.switch_other_student": "Le changement de groupe concerne un autre élève.",
    "db.left_needs_date": "Une inscription terminée doit avoir une date de sortie.",
    "db.group_full": "Le groupe est complet.",
    "db.capacity_below_enrolled": "La capacité est inférieure aux inscriptions actuelles.",
    "db.group_exceeds_room": "La salle est trop petite pour les élèves inscrits du groupe.",
    "db.room_below_group": (
        "Un groupe qui a cours dans cette salle compte plus d'élèves inscrits que cette capacité."
    ),
    "db.room_full": (
        "La salle de ce groupe est pleine. Choisissez une salle plus grande pour ses créneaux."
    ),
    "db.room_slot_overlap": "Ce créneau chevauche un autre créneau de la salle.",
    "db.group_slot_overlap": "Ce créneau chevauche un autre créneau du groupe.",
    "db.session_group_mismatch": "La séance n'appartient pas au groupe du créneau.",
    "db.session_weekday": "La date de la séance ne correspond pas au jour du créneau.",
    "db.room_session_overlap": "Chevauchement de salles pour cette séance.",
    "db.teacher_session_overlap": "Chevauchement d'enseignants pour cette séance.",
    "db.group_session_overlap": "Chevauchement de groupes pour cette séance.",
    "db.session_cancelled": "Cette séance est annulée.",
    "db.enrollment_wrong_group": "L'élève n'est pas inscrit dans le groupe de cette séance.",
    "db.enrollment_not_valid": "L'inscription n'est pas valable à la date de la séance.",
    "db.subscription_overlap": "Les abonnements se chevauchent.",
    "db.rate_overlap": "Les périodes de taux de l'enseignant se chevauchent.",
    "db.group_teacher_overlap": "Les périodes d'enseignant du groupe se chevauchent.",
    "db.refund_exceeds_paid": "Le remboursement dépasse le montant payé.",
    "db.refund_alloc_exceed": "Les affectations dépassent le montant du remboursement.",
    "db.refund_allocations_immutable": "Les affectations de remboursement ne peuvent pas être modifiées.",
    "db.refund_other_subscription": "Ce paiement ne concerne pas l'abonnement remboursé.",
    "db.refund_other_charge": "Ce paiement ne concerne pas la ligne remboursée.",
    "db.refund_new_pending": "Un nouveau remboursement commence « en attente », sans montant versé.",
    "db.refund_subscription_mismatch": "Le remboursement ne correspond pas à l'abonnement de la ligne.",
    "db.refund_not_approved": "Ce remboursement doit être approuvé par la direction avant d'être versé.",
    "db.refund_amount_mismatch": (
        "Le montant versé ne correspond pas aux paiements remboursés."
    ),
    "db.payout_charge_not_open": "Cette charge n'est pas une charge d'abonnement ouverte.",
    "db.payout_amount_mismatch": "Le montant doit être égal à celui de la charge.",
    "db.payout_charge_other_group": "Cette charge appartient à un autre groupe.",
    "db.payout_wrong_teacher": "L'enseignant n'était pas celui du groupe à la date d'imputation.",
    "db.payout_not_draft": "Le paiement enseignant n'est plus un brouillon.",
    "db.payout_locked": "Le paiement enseignant est verrouillé.",
    "db.payout_period": "La date d'imputation est hors de la période de paiement.",
    "db.payout_rate_mismatch": "Le taux ne correspond pas au taux de l'enseignant au début du mois.",
    "db.payout_back_to_draft": "Un paiement enseignant approuvé ne redevient pas un brouillon.",
    "db.payout_approve_not_draft": "Seul un brouillon peut être approuvé.",
    "db.payout_totals_mismatch": "Les totaux du paiement enseignant ne correspondent pas à ses lignes.",
    "db.payout_not_approved": "Ce paiement enseignant doit être approuvé avant d'être versé.",
    "db.payout_paid_mismatch": "Le montant versé doit être le montant dû, avec son numéro.",
    "nav.dashboard": "Tableau de bord",
    "nav.students": "Élèves",
    "nav.groups": "Groupes",
    "nav.subscriptions": "Abonnements",
    "nav.timetable": "Emploi du temps",
    "nav.attendance": "Présences",
    "nav.payments": "Paiements",
    "nav.teachers": "Enseignants",
    "nav.payouts": "Paiements enseignants",
    "nav.reports": "Rapports",
    "nav.sms": "SMS",
    "nav.settings": "Paramètres",
    "login.title": "Connexion",
    "login.username": "Nom d'utilisateur",
    "login.password": "Mot de passe",
    "login.submit": "Se connecter",
    "login.caption": "Connectez-vous pour continuer.",
    "first_run.title": "Première configuration",
    "first_run.school_name": "Nom de l'école",
    "first_run.username": "Nom d'utilisateur du directeur",
    "first_run.password": "Mot de passe",
    "first_run.password_confirm": "Confirmer le mot de passe",
    "first_run.submit": "Créer le compte",
    "first_run.caption": (
        "Créez le compte du directeur. Les comptes de la réception s'ajoutent ensuite "
        "dans les paramètres."
    ),
    "main.ready": "Prêt",
    "main.user_status": "Connecté : {username} · {role}",
    "main.logout": "Se déconnecter",
    "main.back": "← Retour : {page}",
    "main.logout_tip": "Revenir à l'écran de connexion (pour changer d'utilisateur).",
    "page.placeholder": "Cette page sera disponible dans une prochaine étape.",
    "role.director": "Directeur",
    "role.receptionist": "Réceptionniste",
    "user_status.active": "Actif",
    "user_status.disabled": "Désactivé",
    "users.title": "Utilisateurs",
    "users.caption": "Comptes qui peuvent se connecter à Tadris sur cet ordinateur.",
    "users.new": "Nouvel utilisateur",
    "users.created": "Utilisateur créé : {username}",
    "users.col.username": "Nom d'utilisateur",
    "users.col.role": "Rôle",
    "users.col.status": "Statut",
    "users.col.created": "Créé le",
    "user_dialog.title": "Nouvel utilisateur",
    "user_dialog.username": "Nom d'utilisateur",
    "user_dialog.password": "Mot de passe",
    "user_dialog.password_confirm": "Confirmer le mot de passe",
    "user_dialog.role": "Rôle",
    "user_dialog.submit": "Créer l'utilisateur",
    "action.cancel": "Annuler",
    "action.save": "Enregistrer",
    "action.edit": "Modifier",
    "action.back": "← Élèves",
    "student_status.active": "Actif",
    "student_status.inactive": "Inactif",
    "students.new": "Nouvel élève",
    "students.search": "Rechercher par nom, numéro ou téléphone",
    "students.filter.active": "Actifs",
    "students.filter.inactive": "Inactifs",
    "students.filter.all": "Tous",
    "students.col.number": "N°",
    "students.col.last_name": "Nom",
    "students.col.first_name": "Prénom",
    "students.col.birth_date": "Naissance",
    "students.col.contact": "Contact principal",
    "students.col.phone": "Téléphone",
    "students.col.status": "Statut",
    "students.count": "{count} élève(s)",
    "students.empty": "Aucun élève pour l'instant. Cliquez sur « Nouvel élève » pour inscrire le premier.",
    "students.no_match": "Aucun élève ne correspond à cette recherche.",
    "students.created": "Élève créé : {name} ({number})",
    "students.updated": "Élève modifié : {name}",
    "students.deactivated": "Élève désactivé : {name}",
    "students.reactivated": "Élève réactivé : {name}",
    "student_dialog.new_title": "Nouvel élève",
    "student_dialog.edit_title": "Modifier l'élève",
    "student_dialog.last_name": "Nom",
    "student_dialog.first_name": "Prénom",
    "student_dialog.birth_date": "Date de naissance",
    "student_dialog.birth_placeholder": "jj/mm/aaaa",
    "date.pick": "Choisir dans le calendrier (Alt+↓)",
    "student_dialog.notes": "Remarques",
    "student_dialog.contact_section": "Contact principal (facultatif)",
    "student_dialog.contact_caption": "Parent ou tuteur à joindre. D'autres contacts s'ajoutent ensuite.",
    "student_dialog.submit_new": "Créer l'élève",
    "student_dialog.submit_anyway": "Créer quand même",
    "student_dialog.save_anyway": "Enregistrer quand même",
    "student_dialog.duplicates": "Élève peut-être déjà enregistré :",
    "student_dialog.duplicate_name": "{name} ({number}), même nom",
    "student_dialog.duplicate_phone": "{name} ({number}), même téléphone (frère ou sœur ?)",
    "student_dialog.duplicates_hint": "Vérifiez avant de continuer.",
    "student_detail.number": "N° {number}",
    "student_detail.born": "Né(e) le {date}",
    "student_detail.since": "Fiche créée le {date}",
    "student_detail.deactivate": "Désactiver",
    "student_detail.reactivate": "Réactiver",
    "student_detail.confirm_deactivate_title": "Désactiver l'élève",
    "student_detail.confirm_deactivate": (
        "Désactiver {name} ({number}) ? L'élève n'est pas supprimé et pourra être réactivé."
    ),
    "student_detail.tab.registration": "Inscription",
    "student_detail.tab.groups": "Groupes",
    "student_detail.tab.subscriptions": "Abonnements",
    "student_detail.tab.payments": "Paiements",
    "student_detail.tab.refunds": "Remboursements",
    "student_detail.tab.attendance": "Présences",
    "student_detail.tab.contacts": "Contacts",
    "attendance_status.present": "Présent",
    "attendance_status.late": "En retard",
    "attendance_status.absent": "Absent",
    "attendance_status.excused": "Excusé",
    "attendance_view.back": "← Présences",
    "attendance_view.when": "{day} {date}, {start} – {end}",
    "attendance_view.where": "{room} · {teacher}",
    "attendance_view.print": "Imprimer la feuille",
    "attendance_view.all_present": "Non notés → présents",
    "attendance_view.col.student": "Élève",
    "attendance_view.col.number": "N°",
    "attendance_view.col.note": "Remarque",
    "attendance_view.col.mark": "Présence",
    "attendance_view.trial": "Essai",
    "attendance_view.not_renewed": "Mois non renouvelé",
    "attendance_view.empty": "Aucun élève dans ce groupe à la date de la séance.",
    "attendance_view.cancelled": "Séance annulée ({reason}) : pas de présences à noter.",
    "attendance_view.summary": (
        "{present} présent(s) · {late} en retard · {absent} absent(s) · {excused} excusé(s) · "
        "{unmarked} non noté(s)"
    ),
    "attendance_view.saved": "Présences enregistrées ({count} changement(s))",
    "attendance_view.leave_title": "Présences non enregistrées",
    "attendance_view.leave": "Des présences ont été modifiées sans être enregistrées. Quitter quand même ?",
    "attendance_view.leave_action": "Quitter sans enregistrer",
    "student_attendance.col.date": "Date",
    "student_attendance.col.time": "Horaire",
    "student_attendance.col.group": "Groupe",
    "student_attendance.col.status": "Présence",
    "student_attendance.summary": (
        "{present} présent(s) · {late} en retard · {absent} absence(s) · {excused} excusée(s)"
    ),
    "student_attendance.empty": "Aucune présence notée pour cet élève.",
    "session_status.planned": "Prévue",
    "session_status.held": "Tenue",
    "session_status.cancelled": "Annulée",
    "sessions_page.day": "Jour",
    "sessions_page.week": "Semaine",
    "sessions_page.today": "Aujourd'hui",
    "sessions_page.all_groups": "Tous les groupes",
    "sessions_page.all_teachers": "Tous les enseignants",
    "sessions_page.period_day": "{day} {date}",
    "sessions_page.period_week": "Semaine du {first} au {last}",
    "sessions_page.col.date": "Date",
    "sessions_page.col.time": "Horaire",
    "sessions_page.col.group": "Groupe",
    "sessions_page.col.room": "Salle",
    "sessions_page.col.teacher": "Enseignant",
    "sessions_page.col.status": "Statut",
    "sessions_page.col.attendance": "Présences",
    "sessions_page.col.note": "Remarque",
    "sessions_page.empty": (
        "Aucune séance sur cette période. Les séances sont créées à partir de l'emploi du temps "
        "pour les 14 prochains jours (« Régénérer »)."
    ),
    "sessions_page.recorded": "{done} / {total}",
    "sessions_page.substitute_mark": "remplaçant",
    "sessions_page.note.makeup_of": "Rattrapage du {date}",
    "sessions_page.note.made_up": "Rattrapée le {date}",
    "sessions_page.cancel": "Annuler la séance",
    "sessions_page.restore": "Rétablir",
    "sessions_page.makeup": "Rattrapage…",
    "sessions_page.substitute": "Remplaçant…",
    "sessions_page.week_sheet": "Feuille de la semaine",
    "sessions_page.week_sheet_hint": "Choisissez d'abord un groupe dans le filtre.",
    "sessions_page.regenerate": "Régénérer",
    "sessions_page.generated": "{count} séance(s) créée(s) à partir de l'emploi du temps",
    "sessions_page.conflicts": "{count} séance(s) non créée(s) à cause d'un conflit :\n{lines}",
    "sessions_page.conflict_line": "• {date} : {message}",
    "sessions_page.cancelled": "Séance annulée : {group}",
    "sessions_page.restored": "Séance rétablie : {group}",
    "sessions_page.made_up": "Rattrapage prévu : {group}, le {date} à {start}",
    "sessions_page.teacher_set": "Enseignant de la séance modifié : {group}",
    "session_dialog.what": "{group} · {date} de {start} à {end}",
    "cancel_session_dialog.title": "Annuler la séance",
    "cancel_session_dialog.submit": "Annuler la séance",
    "cancel_session_dialog.placeholder": "Ex. : enseignant malade, grève",
    "makeup_dialog.title": "Séance de rattrapage",
    "makeup_dialog.submit": "Prévoir le rattrapage",
    "makeup_dialog.caption": "Séance annulée : {what} ({reason}).",
    "makeup_dialog.date": "Date",
    "makeup_dialog.start": "Début",
    "makeup_dialog.end": "Fin",
    "makeup_dialog.room": "Salle",
    "makeup_dialog.teacher": "Enseignant",
    "substitute_dialog.title": "Remplaçant",
    "substitute_dialog.caption": (
        "Pour cette séance seulement : {what}. Choisir l'enseignant du groupe retire le "
        "remplaçant."
    ),
    "substitute_dialog.teacher": "Enseignant de la séance",
    "subscription_state.upcoming": "À venir",
    "subscription_state.active": "En cours",
    "subscription_state.expiring": "Se termine bientôt",
    "subscription_state.ended": "Terminé",
    "subscription_state.cancelled": "Annulé",
    "subscriptions.period": "du {start} au {end}",
    "subscriptions.col.group": "Groupe",
    "subscriptions.col.period": "Période",
    "subscriptions.col.price": "Prix",
    "subscriptions.col.due": "Reste à payer",
    "subscriptions.col.status": "Statut",
    "subscriptions.summary": "Reste à payer sur les abonnements : {due}",
    "subscriptions.free": "Gratuit",
    "subscriptions.empty": (
        "Aucun abonnement. Le premier mois est créé à l'inscription dans un groupe (ou à la "
        "confirmation d'un essai)."
    ),
    "subscriptions.renew": "Renouveler",
    "subscriptions.cancel": "Annuler l'abonnement",
    "subscriptions.start": "Nouvel abonnement",
    "subscriptions.renewed": "Abonnement renouvelé : {group}, {period}",
    "subscriptions.started": "Abonnement créé : {group}, {period}",
    "subscriptions.cancelled_msg": "Abonnement annulé : {group}",
    "subscriptions_page.title": "Abonnements",
    "subscriptions_page.caption": (
        "Les élèves encore dans leur groupe dont le mois se termine, est terminé, ou qui n'ont "
        "plus d'abonnement. Double-cliquez sur une ligne pour ouvrir la fiche de l'élève."
    ),
    "subscriptions_page.tab.soon": "Se terminent dans 7 jours ({count})",
    "subscriptions_page.tab.lapsed": "Terminés, non renouvelés ({count})",
    "subscriptions_page.tab.missing": "Sans abonnement ({count})",
    "payment_state.kept": "Encaissé",
    "payment_state.voided": "Annulé",
    "payments_tab.summary": "Reste à payer {due} · en retard {overdue} · crédit {credit}",
    "payments_tab.summary_credit": "Rien à payer · crédit disponible {credit}",
    "payments_tab.receive": "Encaisser un paiement",
    "payments_tab.nothing_due": "Rien à payer pour le moment.",
    "payments_tab.history": "Paiements reçus",
    "payments_tab.empty": "Aucun paiement. Utilisez « Encaisser un paiement » pour le premier.",
    "payments_tab.print": "Imprimer le reçu",
    "payments_tab.void": "Annuler le paiement",
    "payments_tab.received": "Paiement de {amount} enregistré : reçu {number}",
    "payments_tab.voided": "Paiement {number} ({amount}) annulé",
    "payments_tab.col.item": "Désignation",
    "payments_tab.col.due_date": "Échéance",
    "payments_tab.col.amount": "Montant",
    "payments_tab.col.paid": "Payé",
    "payments_tab.col.left": "Reste",
    "payments_tab.col.date": "Date",
    "payments_tab.col.receipt": "Reçu",
    "payments_tab.col.method": "Mode",
    "payments_tab.col.cashier": "Reçu par",
    "payments_tab.col.status": "Statut",
    "payment_dialog.title": "Encaisser un paiement",
    "payment_dialog.submit": "Encaisser",
    "payment_dialog.submit_amount": "Encaisser {amount}",
    "payment_dialog.summary": (
        "{name} : reste à payer {due}, dont {overdue} en retard. Crédit disponible : {credit}."
    ),
    "payment_dialog.amount": "Montant reçu",
    "payment_dialog.method": "Mode de paiement",
    "payment_dialog.payer": "Payé par",
    "payment_dialog.no_payer": "— (non précisé)",
    "payment_dialog.choose": "Choisir les lignes à payer (sinon : les plus anciennes d'abord)",
    "payment_dialog.nothing_due": (
        "Rien à payer pour le moment : le montant sera gardé en crédit pour les prochains mois."
    ),
    "payment_dialog.col.item": "Désignation",
    "payment_dialog.col.due_date": "Échéance",
    "payment_dialog.col.left": "Reste dû",
    "payment_dialog.col.credit": "Par le crédit",
    "payment_dialog.col.this": "Ce paiement",
    "payment_dialog.col.after": "Reste après",
    "payment_dialog.credit_used": "Le crédit déjà versé paie {amount}.",
    "payment_dialog.to_credit": "{amount} seront gardés en crédit.",
    "payment_dialog.left_after": "Reste à payer après ce paiement : {amount}.",
    "void_payment_dialog.title": "Annuler le paiement",
    "void_payment_dialog.submit": "Annuler le paiement",
    "void_payment_dialog.caption": (
        "Le reçu {number} de {amount} ({name}, le {date}) sera marqué annulé. Ce qu'il payait "
        "redevient dû. Le paiement reste dans l'historique."
    ),
    "void_payment_dialog.reason": "Motif",
    "void_payment_dialog.placeholder": "Ex. : chèque sans provision, erreur de montant",
    "payments_page.title": "Paiements",
    "payments_page.caption": (
        "Les élèves en retard de paiement et la caisse du jour. Double-cliquez sur une ligne "
        "pour ouvrir la fiche de l'élève et encaisser."
    ),
    "payments_page.tab.debtors": "Élèves en retard",
    "payments_page.tab.cash": "Caisse du jour",
    "payments_page.tab.refunds": "Remboursements à traiter ({count})",
    "debtors.group": "Groupe",
    "debtors.all_groups": "Tous les groupes",
    "debtors.min_amount": "Montant minimum",
    "debtors.any_amount": "Tous les montants",
    "debtors.min_days": "Retard minimum (jours)",
    "debtors.total": "{count} élève(s) · {total} en retard",
    "debtors.empty": "Aucun élève en retard de paiement avec ces filtres.",
    "debtors.col.student": "Élève",
    "debtors.col.number": "N°",
    "debtors.col.owed": "En retard",
    "debtors.col.due": "Reste total",
    "debtors.col.since": "Depuis le",
    "debtors.col.days": "Jours",
    "cash.total": "Caisse du {date} : {total} ({count} paiement(s))",
    "cash.by_method": "Par mode : {parts}",
    "cash.by_cashier": "Par caissier : {parts}",
    "cash.voided": "Annulés (non comptés) : {count} paiement(s), {total}",
    "cash.refunded": (
        "Remboursements versés : {count}, {total}. Espèces à avoir en caisse pour la "
        "journée : {drawer}."
    ),
    "cash.teachers_paid": (
        "Enseignants payés : {count}, {total}. Espèces à avoir en caisse pour la journée : "
        "{drawer}."
    ),
    "cash.empty": "Aucun paiement reçu ce jour-là.",
    "cash.col.time": "Heure",
    "cash.col.receipt": "Reçu",
    "cash.col.student": "Élève",
    "cash.col.amount": "Montant",
    "cash.col.method": "Mode",
    "cash.col.cashier": "Reçu par",
    "cash.col.status": "Statut",
    "refund_status.pending": "En attente",
    "refund_status.approved": "Approuvé",
    "refund_status.paid": "Versé",
    "refund_status.rejected": "Refusé",
    "refunds.title": "Remboursements",
    "refunds.empty": "Aucun remboursement.",
    "refunds.queue_empty": "Aucun remboursement en attente de décision ou de versement.",
    "refunds.request": "Demander un remboursement",
    "refunds.requested": "Demande de remboursement enregistrée : la direction doit l'approuver",
    "refunds.approve": "Approuver",
    "refunds.reject": "Refuser",
    "refunds.pay": "Rembourser",
    "refunds.print": "Imprimer le bon",
    "refunds.approved": "Remboursement approuvé : {line}",
    "refunds.rejected": "Remboursement refusé : {line}",
    "refunds.paid": "Remboursement {number} de {amount} versé",
    "refunds.col.date": "Demandé le",
    "refunds.col.student": "Élève",
    "refunds.col.line": "Ligne",
    "refunds.col.amount": "Montant",
    "refunds.col.status": "Statut",
    "refunds.col.number": "N°",
    "refund_dialog.title": "Demander un remboursement",
    "refund_dialog.submit": "Envoyer la demande",
    "refund_dialog.caption": (
        "Rend de l'argent déjà payé sur une ligne, après approbation de la direction. Le "
        "montant proposé est ce qui a été payé pour les jours non utilisés."
    ),
    "refund_dialog.charge": "Ligne",
    "refund_dialog.unused_from": "Non utilisé à partir du",
    "refund_dialog.amount": "Montant à rendre",
    "refund_dialog.reason": "Motif",
    "refund_dialog.reason_placeholder": "Ex. : départ de l'élève, inscrit par erreur",
    "refund_dialog.info": (
        "Payé {paid} · déjà rendu {refunded} · déjà demandé {reserved} · peut être rendu "
        "{refundable}. Proposé : {suggestion}."
    ),
    "refund_dialog.nothing": "Rien à rendre : aucune ligne n'a de montant payé et non rendu.",
    "refund_decision.caption": (
        "{student} · {line} : {amount} demandés par {by} (proposé : {suggestion}). Motif : "
        "{reason}."
    ),
    "approve_refund.title": "Approuver le remboursement",
    "approve_refund.submit": "Approuver",
    "approve_refund.amount": "Montant approuvé",
    "reject_refund.title": "Refuser le remboursement",
    "reject_refund.submit": "Refuser",
    "reject_refund.reason": "Motif du refus",
    "reject_refund.placeholder": "Ex. : le mois est déjà bien entamé",
    "pay_out.title": "Rembourser",
    "pay_out.submit": "Rembourser {amount}",
    "pay_out.method": "Rendu en",
    "pay_out.caption": (
        "Remettre {amount} pour {student} ({line}). Le bon de remboursement s'imprime pour "
        "être signé par la personne qui reçoit l'argent."
    ),
    "subscriptions_page.col.student": "Élève",
    "subscriptions_page.col.number": "N°",
    "subscriptions_page.col.group": "Groupe",
    "subscriptions_page.col.period": "Mois actuel",
    "subscriptions_page.col.entry": "Entrée",
    "subscriptions_page.col.due": "Reste à payer",
    "subscriptions_page.empty.soon": "Aucun mois ne se termine dans les 7 prochains jours.",
    "subscriptions_page.empty.lapsed": "Tous les mois terminés ont été renouvelés.",
    "subscriptions_page.empty.missing": "Tous les élèves ont un abonnement.",
    "subscriptions_page.renew": "Renouveler…",
    "bulk_renew.submit": "Renouveler",
    "bulk_renew.caption": (
        "Chaque mois suivant commence à la fin du mois actuel, au prix actuel du groupe. "
        "Décochez les élèves qui s'arrêtent."
    ),
    "bulk_renew.col.student": "Élève",
    "bulk_renew.col.group": "Groupe",
    "bulk_renew.col.current": "Mois actuel",
    "bulk_renew.col.next": "Nouveau mois",
    "bulk_renew.col.price": "Prix",
    "bulk_renew.total": "{count} abonnement(s) à renouveler · {total}",
    "bulk_renew.done": "{count} abonnement(s) renouvelé(s)",
    "group_detail.renew": "Renouveler les abonnements",
    "group_detail.renew_title": "Renouveler les abonnements · {name}",
    "group_detail.nothing_to_renew": (
        "Aucun abonnement à renouveler dans ce groupe : aucun mois terminé ni se terminant dans "
        "les 7 jours."
    ),
    "renew_dialog.title": "Renouveler l'abonnement",
    "renew_dialog.submit": "Renouveler",
    "renew_dialog.caption": (
        "{group} · mois actuel {period}. Le mois suivant commence à sa fin, ou plus tard après "
        "une interruption."
    ),
    "renew_dialog.start": "Début du mois",
    "renew_dialog.preview": "Nouveau mois : {period} · {price} (prix actuel du groupe)",
    "start_dialog.title": "Nouvel abonnement",
    "start_dialog.submit": "Créer",
    "start_dialog.caption": (
        "Pour un groupe où l'élève n'a plus d'abonnement (par exemple après une annulation)."
    ),
    "start_dialog.group": "Groupe",
    "cancel_subscription_dialog.title": "Annuler l'abonnement",
    "cancel_subscription_dialog.submit": "Annuler l'abonnement",
    "cancel_subscription_dialog.caption": (
        "Le mois {period} de {group} ({price}) sera annulé, ainsi que son montant dû. "
        "Impossible une fois payé en partie ou compté dans un paiement enseignant."
    ),
    "enrollment_status.trial": "Essai",
    "enrollment_status.active": "Actif",
    "enrollment_status.left": "Sorti",
    "enrollment_status.switched": "Changé de groupe",
    "student_groups.enroll": "Inscrire dans un groupe",
    "student_groups.confirm_trial": "Confirmer l'essai",
    "student_groups.switch": "Changer de groupe",
    "student_groups.leave": "Sortir du groupe",
    "student_groups.col.group": "Groupe",
    "student_groups.col.status": "Statut",
    "student_groups.col.entry": "Entrée",
    "student_groups.col.exit": "Sortie",
    "student_groups.col.note": "Remarque",
    "student_groups.note.other_level": "Autre niveau (inscrit en {level})",
    "student_groups.note.from": "Vient de {group}",
    "student_groups.note.after_trial": "Commencé en essai",
    "student_groups.not_registered": (
        "Inscrivez d'abord l'élève pour l'année (onglet Inscription), puis dans ses groupes."
    ),
    "student_groups.empty": (
        "Aucun groupe pour l'instant. Cliquez sur « Inscrire dans un groupe ». Un élève peut être "
        "dans plusieurs groupes."
    ),
    "student_groups.enrolled": "{name} inscrit(e) dans {group}",
    "student_groups.trial_confirmed": "Essai confirmé : {group}",
    "student_groups.switched": "Changement de groupe : {old} → {new}",
    "student_groups.left": "Sorti(e) du groupe {group}",
    "enroll_dialog.title": "Inscrire dans un groupe",
    "enroll_dialog.submit": "Inscrire",
    "enroll_dialog.caption": "{name} · choisissez un groupe :",
    "enroll_dialog.col.group": "Groupe",
    "enroll_dialog.col.teacher": "Enseignant",
    "enroll_dialog.col.free": "Places libres",
    "enroll_dialog.col.note": "Remarque",
    "enroll_dialog.none": (
        "Aucun groupe disponible : l'élève est déjà dans tous les groupes de son niveau, ou ils "
        "sont complets ou clôturés. Seuls les groupes du niveau de l'élève sont proposés."
    ),
    "enroll_dialog.full_hidden": "{count} groupe(s) complet(s) non affiché(s).",
    "enroll_dialog.date": "Date d'entrée",
    "enroll_dialog.trial": "Essai gratuit (un seul par élève)",
    "enroll_dialog.trial_used": "L'essai gratuit de cet élève a déjà été utilisé.",
    "enroll_dialog.same_subject": "Même matière",
    "enroll_dialog.reason": "Motif de la dérogation (directeur)",
    "enroll_dialog.reason_placeholder": "Ex. : rattrapage, niveau adapté",
    "enroll_dialog.group_required": "Choisissez un groupe dans la liste.",
    "switch_dialog.title": "Changer de groupe",
    "switch_dialog.submit": "Changer de groupe",
    "switch_dialog.caption": (
        "Groupe actuel : {group}. L'élève le quitte à cette date et entre le même jour dans le "
        "nouveau groupe (ou à son premier jour s'il n'a pas commencé). Un essai reste un essai."
    ),
    "switch_dialog.date": "Date du changement",
    "leave_dialog.title": "Sortir du groupe",
    "leave_dialog.submit": "Sortir du groupe",
    "leave_dialog.caption": "{name} quitte {group}. Sa place est libérée tout de suite.",
    "leave_dialog.date": "Date de sortie",
    "leave_dialog.reason": "Motif (facultatif)",
    "leave_dialog.reason_placeholder": "Ex. : déménagement",
    "registration_status.active": "Active",
    "registration_status.cancelled": "Annulée",
    "registration_tab.register": "Inscrire pour l'année {label}",
    "registration_tab.change_level": "Changer le niveau",
    "registration_tab.cancel": "Annuler l'inscription",
    "registration_tab.title": "Année {label}",
    "registration_tab.level": "Niveau",
    "registration_tab.fee": "Frais d'inscription",
    "registration_tab.due": "Reste à payer",
    "registration_tab.date": "Inscrit(e) le",
    "registration_tab.groups": "Groupes",
    "registration_tab.not_registered": (
        "Pas encore inscrit(e) pour l'année {label}. L'inscription annuelle vient avant les "
        "groupes."
    ),
    "registration_tab.student_inactive": (
        "Cet élève est désactivé. Réactivez-le pour l'inscrire."
    ),
    "registration_tab.history": "Inscriptions annuelles",
    "registration_tab.col.year": "Année",
    "registration_tab.col.level": "Niveau",
    "registration_tab.col.fee": "Frais",
    "registration_tab.col.status": "Statut",
    "registration_tab.col.date": "Date",
    "registration_tab.registered": "{name} inscrit(e) pour l'année {label}",
    "registration_tab.level_changed": "Niveau modifié",
    "registration_tab.cancelled": "Inscription annuelle de {name} annulée",
    "registration_dialog.title": "Inscription annuelle {label}",
    "registration_dialog.submit": "Inscrire",
    "registration_dialog.caption": "{name} · N° {number}",
    "registration_dialog.level": "Niveau",
    "registration_dialog.choose_level": "Choisir un niveau…",
    "registration_dialog.fee": "Frais d'inscription",
    "registration_dialog.fee_caption": (
        "Montant par défaut : {fee} (Paramètres → École). Vous pouvez le changer pour cet élève ; "
        "0 = sans frais."
    ),
    "change_level_dialog.title": "Changer le niveau",
    "change_level_dialog.caption": (
        "Niveau actuel : {level} ({label}). Possible tant que l'élève n'est dans aucun groupe."
    ),
    "cancel_registration_dialog.title": "Annuler l'inscription annuelle",
    "cancel_registration_dialog.submit": "Annuler l'inscription",
    "cancel_registration_dialog.caption": (
        "L'inscription de {name} pour {label} sera annulée, ainsi que ses frais ({fee}). "
        "L'élève pourra être inscrit à nouveau."
    ),
    "cancel_registration_dialog.reason": "Motif",
    "cancel_registration_dialog.placeholder": "Ex. : erreur de saisie",
    "contacts.add": "Ajouter un contact",
    "contacts.make_main": "Définir comme principal",
    "contacts.unlink": "Retirer",
    "contacts.empty": "Aucun contact. Cliquez sur « Ajouter un contact » pour ajouter un parent ou un tuteur.",
    "contacts.col.name": "Nom",
    "contacts.col.relation": "Lien",
    "contacts.col.phone": "Téléphone",
    "contacts.col.phone_2": "Téléphone 2",
    "contacts.col.sms": "SMS",
    "contacts.col.main": "Principal",
    "contacts.main_badge": "Principal",
    "contacts.sms_yes": "Oui",
    "contacts.sms_no": "Non",
    "contacts.added": "Contact ajouté : {name}",
    "contacts.updated": "Contact modifié : {name}",
    "contacts.main_set": "Contact principal : {name}",
    "contacts.unlinked": "Contact retiré : {name}",
    "contacts.confirm_unlink_title": "Retirer le contact",
    "contacts.confirm_unlink": (
        "Retirer {contact} des contacts de {student} ? Le contact reste enregistré "
        "pour les autres élèves."
    ),
    "contact_dialog.new_title": "Nouveau contact",
    "contact_dialog.edit_title": "Modifier le contact",
    "contact_dialog.full_name": "Nom complet",
    "contact_dialog.relation": "Lien avec l'élève",
    "contact_dialog.phone": "Téléphone",
    "contact_dialog.phone_2": "Téléphone 2",
    "contact_dialog.address": "Adresse",
    "contact_dialog.is_main": "Contact principal",
    "contact_dialog.can_receive_sms": "Peut recevoir des SMS",
    "contact_dialog.main_locked": "Pour changer, désignez un autre contact comme principal.",
    "contact_dialog.shared": "Contact partagé avec : {names}. Les modifications s'appliquent à tous.",
    "contact_dialog.existing": (
        "Ce numéro appartient déjà à {name} (contact de : {students}). "
        "Ce contact sera lié à l'élève sans être modifié."
    ),
    "contact_dialog.existing_no_student": (
        "Ce numéro appartient déjà à {name}. Ce contact sera lié à l'élève sans être modifié."
    ),
    "contact_dialog.link_existing": "Lier ce contact",
    "contact_dialog.create_new": "Créer un nouveau contact",
    "contact_dialog.submit": "Enregistrer le contact",
    "relation.father": "Père",
    "relation.mother": "Mère",
    "relation.guardian": "Tuteur / tutrice",
    "relation.sibling": "Frère / sœur",
    "relation.grandparent": "Grand-parent",
    "relation.self": "L'élève lui-même",
    "confirm.yes": "Confirmer",
    "action.add": "Ajouter",
    "action.rename": "Renommer",
    "action.activate": "Activer",
    "action.deactivate": "Désactiver",
    "action.move_up": "Monter",
    "action.move_down": "Descendre",
    "action.create": "Créer",
    "active.yes": "Actif",
    "active.no": "Désactivé",
    "filter.all": "Tous",
    "filter.all_f": "Toutes",
    "settings.tab.school": "École",
    "settings.tab.users": "Utilisateurs",
    "settings.tab.holidays": "Vacances",
    "holidays.caption": (
        "Les jours sans cours (vacances, jours fériés). Aucune séance n'est prévue ces jours-là."
    ),
    "holidays.col.label": "Libellé",
    "holidays.col.start": "Du",
    "holidays.col.end": "Au",
    "holidays.col.days": "Jours",
    "holidays.empty": "Aucune période de vacances. Ajoutez-en une avec « Nouvelle période ».",
    "holidays.new": "Nouvelle période",
    "holidays.remove": "Supprimer",
    "holidays.saved": "Vacances enregistrées : {label}",
    "holidays.removed": "Vacances supprimées : {label}",
    "holidays.confirm_remove_title": "Supprimer la période",
    "holidays.confirm_remove": "Supprimer « {label} » ? Des séances pourront être prévues ces jours-là.",
    "holiday_dialog.new_title": "Nouvelle période de vacances",
    "holiday_dialog.edit_title": "Modifier la période de vacances",
    "holiday_dialog.label": "Libellé",
    "holiday_dialog.placeholder": "Ex. : Vacances d'hiver, 1er Novembre",
    "holiday_dialog.start": "Du",
    "holiday_dialog.end": "Au (inclus)",
    "holiday_dialog.caption": "Laissez « Au » vide pour un seul jour. Les deux dates sont incluses.",
    "school.caption": "Ces informations figurent en tête des reçus et des documents imprimés.",
    "school.name": "Nom de l'école",
    "school.phone": "Téléphone",
    "school.address": "Adresse",
    "school.hours": "Horaires d'ouverture",
    "school.hours_caption": (
        "Les créneaux de l'emploi du temps doivent tenir dans ces horaires, chaque jour."
    ),
    "school.opens_at": "Ouverture",
    "school.closes_at": "Fermeture",
    "school.saved": "Paramètres de l'école enregistrés",
    "school.fees": "Inscriptions et paiements",
    "school.fees_caption": (
        "Montant proposé à chaque inscription annuelle. L'accueil peut le changer au cas par cas ; "
        "les inscriptions déjà faites gardent leur montant. Au-delà du seuil d'alerte, "
        "l'inscription dans un groupe et le renouvellement affichent la dette en retard de "
        "l'élève (sans bloquer)."
    ),
    "school.registration_fee": "Frais d'inscription par défaut",
    "school.debt_warning": "Alerte de dette à partir de",
    "school.debt_warning_off": "Vide : pas d'alerte",
    "school.debt_warning_invalid": "Le seuil d'alerte de dette est invalide.",
    "settings.tab.years": "Années scolaires",
    "settings.tab.levels": "Niveaux",
    "settings.tab.subjects": "Matières",
    "settings.tab.rooms": "Salles",
    "year_state.open": "Ouverte",
    "year_state.upcoming": "À venir",
    "year_state.closed": "Clôturée",
    "years.caption": (
        "Une seule année est ouverte à la fois. Une année à venir peut déjà recevoir ses "
        "groupes et son emploi du temps."
    ),
    "years.new": "Nouvelle année",
    "years.open": "Ouvrir",
    "years.close": "Clôturer",
    "years.empty": "Aucune année scolaire. Créez la première avec « Nouvelle année ».",
    "years.col.label": "Année",
    "years.col.start": "Début",
    "years.col.end": "Fin",
    "years.col.status": "Statut",
    "years.col.groups": "Groupes",
    "years.created": "Année créée : {label}",
    "years.updated": "Année modifiée : {label}",
    "years.opened": "Année ouverte : {label}",
    "years.closed": "Année clôturée : {label} ({count} groupe(s) clôturé(s))",
    "years.confirm_close_title": "Clôturer l'année",
    "years.confirm_close": (
        "Clôturer {label} ? Ses {count} groupe(s) seront clôturés, leurs élèves en sortiront "
        "et leurs créneaux seront libérés. "
        "Les inscriptions ne seront plus possibles dans cette année."
    ),
    "year_dialog.new_title": "Nouvelle année scolaire",
    "year_dialog.edit_title": "Modifier l'année scolaire",
    "year_dialog.label": "Libellé",
    "year_dialog.start": "Premier jour",
    "year_dialog.end": "Dernier jour",
    "levels.caption": "L'ordre des niveaux est celui des listes et des rapports.",
    "levels.new": "Nouveau niveau",
    "levels.empty": "Aucun niveau. Ajoutez-en un avec « Nouveau niveau » (par exemple 4AM).",
    "subjects.caption": "Une matière désactivée n'est plus proposée pour les nouveaux groupes.",
    "subjects.new": "Nouvelle matière",
    "subjects.empty": "Aucune matière. Ajoutez-en une avec « Nouvelle matière ».",
    "catalog.col.name": "Nom",
    "catalog.col.status": "Statut",
    "catalog.col.groups": "Groupes ouverts",
    "catalog.saved": "Enregistré : {name}",
    "name_dialog.level_new": "Nouveau niveau",
    "name_dialog.level_edit": "Renommer le niveau",
    "name_dialog.subject_new": "Nouvelle matière",
    "name_dialog.subject_edit": "Renommer la matière",
    "name_dialog.name": "Nom",
    "rooms.caption": "La capacité d'une salle limite celle des groupes qui y ont cours.",
    "rooms.new": "Nouvelle salle",
    "rooms.empty": "Aucune salle. Ajoutez-en une avec « Nouvelle salle ».",
    "rooms.col.name": "Salle",
    "rooms.col.capacity": "Places",
    "rooms.col.status": "Statut",
    "rooms.col.slots": "Créneaux",
    "room_dialog.new_title": "Nouvelle salle",
    "room_dialog.edit_title": "Modifier la salle",
    "room_dialog.name": "Nom",
    "room_dialog.capacity": "Nombre de places",
    "teachers.new": "Nouvel enseignant",
    "teachers.back": "← Enseignants",
    "groups.back": "← Groupes",
    "teachers.search": "Rechercher un enseignant",
    "teachers.filter.active": "Actifs",
    "teachers.filter.inactive": "Inactifs",
    "teachers.col.name": "Nom",
    "teachers.col.phone": "Téléphone",
    "teachers.col.rate": "Taux",
    "teachers.col.groups": "Groupes",
    "teachers.col.status": "Statut",
    "teachers.empty": "Aucun enseignant. Ajoutez le premier avec « Nouvel enseignant ».",
    "teachers.no_match": "Aucun enseignant ne correspond à cette recherche.",
    "teachers.count": "{count} enseignant(s)",
    "teachers.created": "Enseignant ajouté : {name}",
    "teachers.updated": "Enseignant modifié : {name}",
    "teachers.rate_set": "Nouveau taux pour {name} : {rate}",
    "teachers.deactivated": "Enseignant désactivé : {name}",
    "teachers.reactivated": "Enseignant réactivé : {name}",
    "teacher_status.active": "Actif",
    "teacher_status.inactive": "Inactif",
    "teacher_detail.hired": "Depuis le {date}",
    "teacher_detail.rate": "Taux actuel : {rate}",
    "teacher_detail.new_rate": "Nouveau taux",
    "teacher_detail.tab.groups": "Groupes",
    "teacher_detail.tab.rates": "Historique des taux",
    "teacher_detail.tab.payouts": "Paiements",
    "teacher_detail.payouts_empty": "Aucun paiement pour cet enseignant.",
    "teacher_detail.groups_empty": "Aucun groupe pour cet enseignant.",
    "teacher_detail.confirm_deactivate_title": "Désactiver l'enseignant",
    "teacher_detail.confirm_deactivate": "Désactiver {name} ? Il ne pourra plus recevoir de groupe.",
    "rates.col.rate": "Taux",
    "rates.col.from": "À partir du",
    "rates.col.to": "Jusqu'au",
    "rates.current": "En cours",
    "rates.empty": "Aucun taux.",
    "teacher_dialog.new_title": "Nouvel enseignant",
    "teacher_dialog.edit_title": "Modifier l'enseignant",
    "teacher_dialog.name": "Nom complet",
    "teacher_dialog.phone": "Téléphone",
    "teacher_dialog.hire_date": "Date d'arrivée",
    "teacher_dialog.rate": "Taux sur les recettes",
    "teacher_dialog.rate_from": "Taux applicable à partir du",
    "teacher_dialog.rate_caption": (
        "Part du prix des abonnements de ses groupes, par exemple 60 %. "
        "Les changements de taux gardent l'historique."
    ),
    "rate_dialog.title": "Nouveau taux",
    "rate_dialog.rate": "Taux",
    "rate_dialog.from": "À partir du",
    "rate_dialog.caption": (
        "Le taux actuel ({rate}) s'arrête la veille. Les mois déjà calculés ne changent pas."
    ),
    "groups.new": "Nouveau groupe",
    "groups.search": "Rechercher un groupe, une matière, un enseignant",
    "groups.filter.year": "Année",
    "groups.filter.level": "Tous les niveaux",
    "groups.filter.subject": "Toutes les matières",
    "groups.filter.open": "Ouverts",
    "groups.filter.closed": "Clôturés",
    "groups.col.name": "Groupe",
    "groups.col.subject": "Matière",
    "groups.col.level": "Niveau",
    "groups.col.teacher": "Enseignant",
    "groups.col.price": "Prix",
    "groups.col.places": "Élèves",
    "groups.col.start": "Début",
    "groups.col.status": "Statut",
    "groups.empty": "Aucun groupe. Créez le premier avec « Nouveau groupe ».",
    "groups.empty_receptionist": "Aucun groupe pour l'instant.",
    "groups.no_match": "Aucun groupe ne correspond à ces filtres.",
    "groups.no_year": (
        "Aucune année scolaire ouverte. Le directeur la crée dans Paramètres, "
        "onglet Années scolaires."
    ),
    "groups.count": "{count} groupe(s)",
    "groups.created": "Groupe créé : {name}",
    "groups.updated": "Groupe modifié : {name}",
    "groups.teacher_changed": "{name} : nouvel enseignant {teacher}",
    "groups.closed_msg": "Groupe clôturé : {name}",
    "groups.reopened": "Groupe rouvert : {name}",
    "group_state.active": "Actif",
    "group_state.upcoming": "À venir",
    "group_state.closed": "Clôturé",
    "group_detail.meta": "{subject} · {level} · {year}",
    "group_detail.teacher": "Enseignant : {teacher}",
    "group_detail.no_teacher": "Pas d'enseignant",
    "group_detail.price": "{price} / mois",
    "group_detail.places": "{enrolled} / {capacity} élèves",
    "group_detail.places_room": (
        "{enrolled} / {seats} élèves (limité par la salle {room}, groupe prévu pour {capacity})"
    ),
    "group_detail.starts": "Début le {date}",
    "group_detail.change_teacher": "Changer d'enseignant",
    "group_detail.close": "Clôturer",
    "group_detail.reopen": "Rouvrir",
    "group_detail.tab.slots": "Créneaux",
    "group_detail.tab.teachers": "Enseignants",
    "group_detail.tab.students": "Élèves",
    "group_students.summary": (
        "{enrolled} / {seats} élèves · {free} place(s) libre(s) · {trials} en essai"
    ),
    "group_students.show_past": "Afficher les anciens élèves ({count})",
    "group_students.col.name": "Élève",
    "group_students.col.number": "N°",
    "group_students.col.status": "Statut",
    "group_students.col.entry": "Entrée",
    "group_students.col.exit": "Sortie",
    "group_students.col.note": "Remarque",
    "group_students.note.switched_in": "Changement de groupe",
    "group_students.empty": (
        "Aucun élève dans ce groupe. Les élèves s'inscrivent depuis leur fiche, onglet Groupes."
    ),
    "group_students.hint": (
        "Pour inscrire, changer de groupe ou faire sortir un élève, ouvrez sa fiche (Élèves → "
        "onglet Groupes)."
    ),
    "group_detail.confirm_close_title": "Clôturer le groupe",
    "group_detail.confirm_close": (
        "Clôturer {name} ? Ses {enrolled} élève(s) en sortiront aujourd'hui, il ne recevra "
        "plus d'élèves et ses créneaux seront libérés. Rouvrir le groupe ne remettra pas les "
        "élèves."
    ),
    "slots.add": "Ajouter un créneau",
    "slots.empty": "Aucun créneau. Ajoutez le premier avec « Ajouter un créneau ».",
    "slots.col.day": "Jour",
    "slots.col.time": "Horaire",
    "slots.col.room": "Salle",
    "slots.col.from": "À partir du",
    "slots.added": "Créneau ajouté",
    "slots.updated": "Créneau modifié",
    "slots.removed": "Créneau retiré",
    "slots.confirm_remove_title": "Retirer le créneau",
    "slots.confirm_remove": "Retirer le créneau du {day} de {start} à {end} ({group}) ?",
    "history.col.teacher": "Enseignant",
    "history.col.from": "À partir du",
    "history.col.to": "Jusqu'au",
    "group_dialog.new_title": "Nouveau groupe",
    "group_dialog.edit_title": "Modifier le groupe",
    "group_dialog.year": "Année scolaire",
    "group_dialog.level": "Niveau",
    "group_dialog.subject": "Matière",
    "group_dialog.name": "Nom du groupe",
    "group_dialog.name_placeholder": "G1",
    "group_dialog.price": "Prix mensuel",
    "group_dialog.capacity": "Places",
    "group_dialog.start": "Date de début",
    "group_dialog.teacher": "Enseignant",
    "group_dialog.price_caption": "Un nouveau prix s'applique aux prochains abonnements seulement.",
    "group_dialog.no_teacher": "Ajoutez d'abord un enseignant dans la page Enseignants.",
    "change_teacher.title": "Changer d'enseignant",
    "change_teacher.teacher": "Nouvel enseignant",
    "change_teacher.from": "À partir du",
    "change_teacher.caption": (
        "{current} reste l'enseignant du groupe jusqu'à la veille. Les recettes sont "
        "attribuées selon la date de chaque abonnement."
    ),
    "slot_dialog.new_title": "Nouveau créneau",
    "slot_dialog.edit_title": "Modifier le créneau",
    "slot_dialog.group": "Groupe",
    "slot_dialog.room": "Salle",
    "slot_dialog.day": "Jour",
    "slot_dialog.start": "Début",
    "slot_dialog.end": "Fin",
    "slot_dialog.remove": "Retirer le créneau",
    "slot_dialog.no_rooms": "Ajoutez d'abord une salle dans Paramètres.",
    "timetable.view.room": "Par salle",
    "timetable.view.group": "Par groupe",
    "timetable.view.teacher": "Par enseignant",
    "timetable.on": "Semaine du",
    "timetable.new": "Nouveau créneau",
    "timetable.empty": (
        "Aucun créneau cette semaine. Double-cliquez sur la grille ou utilisez "
        "« Nouveau créneau »."
    ),
    "timetable.nothing": "Ajoutez d'abord des salles et des groupes.",
    "timetable.hint": "Double-cliquez sur une case vide pour ajouter un créneau.",
    "backup.not_found": "Sauvegarde introuvable.",
    "backup.failed": "La sauvegarde de la base a échoué ({path}).",
    "backup.warning_title": "Sauvegarde",
    "backup.warning": (
        "{error}\n\nL'application continue, mais vos données ne sont pas sauvegardées. "
        "Vérifiez l'espace disque et les droits du dossier, puis redémarrez l'application."
    ),
    "backup.before_migration": (
        "{error}\n\nCette version doit mettre à jour la base, ce qu'elle ne fait jamais sans "
        "copie. Vérifiez l'espace disque et les droits du dossier, puis relancez l'application."
    ),
    "month.1": "Janvier",
    "month.2": "Février",
    "month.3": "Mars",
    "month.4": "Avril",
    "month.5": "Mai",
    "month.6": "Juin",
    "month.7": "Juillet",
    "month.8": "Août",
    "month.9": "Septembre",
    "month.10": "Octobre",
    "month.11": "Novembre",
    "month.12": "Décembre",
    "report.period": "Du {first} au {last}",
    "report.year": "Année {label}",
    "report.year_until": "Année {label}, à payer arrêté au {date}",
    "report.on": "Au {date}",
    "report.dates_order": "La date de fin doit être après la date de début.",
    "report.total": "Total",
    "report.count": "{count} élève(s)",
    "report.fees": "Frais d'inscription",
    "report.col.month": "Mois",
    "report.col.charged": "Facturé",
    "report.col.settled": "Réglé",
    "report.col.left": "Reste à payer",
    "report.col.collected": "Encaissé",
    "report.col.refunded": "Remboursé",
    "report.col.net": "Net encaissé",
    "report.col.group": "Groupe",
    "report.col.groups": "Groupes",
    "report.col.charges": "Mois et frais",
    "report.col.student": "Élève",
    "report.col.students": "Élèves",
    "report.col.number": "N°",
    "report.col.age": "{low} à {high} j",
    "report.col.age_over": "Plus de {days} j",
    "report.col.total": "Total",
    "report.col.sessions": "Séances",
    "report.col.present": "Présents",
    "report.col.late": "Retards",
    "report.col.absent": "Absents",
    "report.col.excused": "Excusés",
    "report.col.rate": "Taux de présence",
    "report.col.teacher": "Enseignant",
    "report.col.paid": "Payé",
    "report.col.waiting": "En attente",
    "report.col.months_open": "Mois à préparer",
    "report.col.not_prepared": "À préparer",
    "report.col.to_pay": "Reste à payer",
    "report.col.last_name": "Nom",
    "report.col.first_name": "Prénom",
    "report.col.birth": "Naissance",
    "report.col.level": "Niveau",
    "report.col.contact": "Contact principal",
    "report.col.phone": "Téléphone",
    "report.col.status": "Statut",
    "report.col.owed": "En retard",
    "report.col.when": "Date",
    "report.col.user": "Utilisateur",
    "report.col.action": "Action",
    "report.col.entity": "Élément",
    "report.col.entity_id": "N° élément",
    "report.col.detail": "Détail",
    "report.revenue_month.title": "Recettes par mois",
    "report.revenue.note": (
        "Facturé : les mois et frais qui commencent dans le mois (annulés exclus). Réglé : ce "
        "que les paiements non annulés ont payé sur ces mois et frais, quelle que soit la date "
        "du paiement. Encaissé : l'argent reçu dans le mois, quel que soit ce qu'il paie. "
        "Remboursé : l'argent rendu dans le mois."
    ),
    "report.revenue_group.title": "Recettes par groupe",
    "report.revenue_group.note": (
        "Les mois d'un groupe et les frais d'inscription qui commencent dans la période "
        "(annulés exclus) ; réglé : ce que les paiements non annulés ont payé dessus."
    ),
    "report.debtors.title": "Retards de paiement par ancienneté",
    "report.debtors.note": (
        "Chaque mois ou frais en retard compte depuis son échéance ; l'avoir de l'élève paie "
        "d'abord les plus anciens. Les mois à venir ne sont pas en retard."
    ),
    "report.attendance_group.title": "Présences par groupe",
    "report.attendance_student.title": "Présences par élève",
    "report.attendance.note": (
        "Taux de présence : (présents + retards) / (présents + retards + absents). Les "
        "absences excusées ne comptent pas ; les séances annulées non plus."
    ),
    "report.teachers.title": "Synthèse enseignants",
    "report.teachers.note": (
        "Groupes et élèves : aujourd'hui. Payé : les paiements versés pendant l'année. En "
        "attente : brouillons et paiements approuvés. À préparer : les mois commencés jusqu'à "
        "aujourd'hui qu'aucun paiement ne contient encore, au taux de leur premier jour."
    ),
    "report.students.title": "Liste des élèves",
    "report.students.note": "Groupes : inscriptions en cours (essai compris). En retard : ce "
                            "qui est échu et pas payé, après l'avoir.",
    "report.audit.title": "Journal des opérations",
    "report.audit.limit": "Seules les {limit} opérations les plus récentes sont affichées : "
                          "réduisez la période ou filtrez.",
    "audit.system": "Système",
    "audit.before": "avant {value}",
    "audit.after": "après {value}",
    "audit.family.attendance": "Présences",
    "audit.family.backup": "Sauvegardes",
    "audit.family.contact": "Contacts",
    "audit.family.enrollment": "Inscriptions aux groupes",
    "audit.family.group": "Groupes",
    "audit.family.holiday": "Vacances",
    "audit.family.level": "Niveaux",
    "audit.family.payment": "Paiements",
    "audit.family.payout": "Paiements enseignants",
    "audit.family.refund": "Remboursements",
    "audit.family.registration": "Inscriptions",
    "audit.family.report": "Rapports exportés",
    "audit.family.room": "Salles",
    "audit.family.school_year": "Années scolaires",
    "audit.family.session": "Séances",
    "audit.family.settings": "Paramètres",
    "audit.family.slot": "Emploi du temps",
    "audit.family.student": "Élèves",
    "audit.family.subject": "Matières",
    "audit.family.subscription": "Abonnements",
    "audit.family.teacher": "Enseignants",
    "audit.family.user": "Utilisateurs",
    "dashboard.title": "Tableau de bord",
    "dashboard.today": "Aujourd'hui, {date}",
    "dashboard.see_all": "Voir tout",
    "dashboard.see_count": "Voir les {count}",
    "dashboard.card.sessions": "Séances aujourd'hui",
    "dashboard.card.sessions_left": "{count} encore à venir",
    "dashboard.card.renew": "Abonnements à renouveler",
    "dashboard.card.renew_detail": "{ending} finissent dans 7 jours · {lapsed} non renouvelés",
    "dashboard.card.debt": "Retards de paiement",
    "dashboard.card.debt_detail": "{count} élève(s) en retard",
    "dashboard.card.money": "Encaissé ce mois",
    "dashboard.card.money_detail": "Facturé {charged} · réglé {settled} · remboursé {refunded}",
    "dashboard.card.fill": "Remplissage des groupes",
    "dashboard.card.fill_detail": "{enrolled} élèves pour {seats} places",
    "dashboard.sessions": "Séances du jour",
    "dashboard.sessions_empty": "Aucune séance aujourd'hui.",
    "dashboard.ending": "Abonnements qui finissent cette semaine",
    "dashboard.ending_empty": "Aucun abonnement ne finit dans les 7 jours.",
    "dashboard.debtors": "Plus gros retards",
    "dashboard.debtors_empty": "Aucun retard de paiement.",
    "dashboard.groups": "Remplissage des groupes",
    "dashboard.groups_empty": "Aucun groupe en cours.",
    "dashboard.days": "{days} j",
    "dashboard.col.time": "Heure",
    "dashboard.col.group": "Groupe",
    "dashboard.col.room": "Salle",
    "dashboard.col.teacher": "Enseignant",
    "dashboard.col.status": "Statut",
    "dashboard.col.student": "Élève",
    "dashboard.col.period": "Mois",
    "dashboard.col.due": "Reste à payer",
    "dashboard.col.owed": "En retard",
    "dashboard.col.since": "Retard",
    "dashboard.col.enrolled": "Élèves",
    "dashboard.col.seats": "Places",
    "dashboard.col.fill": "Remplissage",
    "reports_page.title": "Rapports",
    "reports_page.caption": (
        "Chaque rapport s'affiche ici et s'exporte en PDF (pour l'imprimer) ou en Excel. "
        "Les montants viennent des paiements, mois et remboursements enregistrés."
    ),
    "report.tab.revenue": "Recettes",
    "report.tab.debtors": "Retards",
    "report.tab.attendance": "Présences",
    "report.tab.teachers": "Enseignants",
    "report.tab.students": "Élèves",
    "report.tab.audit": "Journal",
    "report.pdf": "PDF",
    "report.excel": "Excel",
    "report.exported": "Rapport enregistré : {file}",
    "report.empty": "Rien à afficher pour ces filtres.",
    "report.no_year": "Créez d'abord une année scolaire dans Paramètres.",
    "report.entity_invalid": "Le n° d'élément doit être un nombre.",
    "report.view.month": "Par mois",
    "report.view.group": "Par groupe",
    "report.view.student": "Par élève",
    "report.whole_year": "Toute l'année",
    "report.all_groups": "Tous les groupes",
    "report.all_users": "Tous",
    "report.all_families": "Toutes",
    "report.status.active": "Actifs",
    "report.status.inactive": "Inactifs",
    "report.status.all": "Tous",
    "report.filter.year": "Année scolaire",
    "report.filter.view": "Affichage",
    "report.filter.month": "Mois",
    "report.filter.group": "Groupe",
    "report.filter.from": "Du",
    "report.filter.to": "Au",
    "report.filter.status": "Élèves",
    "report.filter.user": "Utilisateur",
    "report.filter.family": "Type d'opération",
    "report.filter.entity": "N° élément",
    "report.filter.any": "Tous",
    "report.audit.pick": "Choisissez une ligne pour voir ce qui a été enregistré.",
    "report.audit.heading": "{action} · {entity} n° {id} · {user}, le {when}",
    "report.audit.old": "Avant :",
    "report.audit.new": "Après :",
}
