import json
import re
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class SpaAppointment(models.Model):
    _name = 'spa.appointment'
    _description = 'Lịch hẹn và liệu trình Spa'

    name = fields.Char(string='Lịch hẹn', compute='_compute_name', store=True)
    customer_id = fields.Many2one(
        'res.partner',
        string='Khách hàng',
        required=True,
        ondelete='restrict',
    )
    customer_phone = fields.Char(
        string='Số điện thoại',
    )
    customer_address = fields.Char(
        string='Địa chỉ',
        related='customer_id.street',
        readonly=False,
    )
    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Nhân viên phụ trách',
        domain=[('active', '=', True)],
        ondelete='restrict',
    )
    room_id = fields.Many2one(
        'spa.room',
        string='Phòng',
        domain=[('active', '=', True)],
        ondelete='restrict',
    )
    bed_id = fields.Many2one(
        'spa.bed',
        string='Giường',
        domain="[('room_id', '=', room_id), ('active', '=', True)]",
        ondelete='restrict',
    )
    available_room_ids = fields.Many2many(
        'spa.room',
        compute='_compute_available_resources',
    )
    available_bed_ids = fields.Many2many(
        'spa.bed',
        compute='_compute_available_resources',
    )
    resource_grid = fields.Json(compute='_compute_available_resources')
    booking_source = fields.Selection([
        ('facebook', 'Facebook / Fanpage'),
        ('zalo', 'Zalo'),
        ('website', 'Website'),
        ('phone', 'Gọi điện'),
        ('walk_in', 'Đến trực tiếp'),
    ], string='Nguồn booking')
    service_id = fields.Many2one('spa.service', string='Dịch vụ cũ')
    service_product_id = fields.Many2one(
        'product.template',
        string='Dịch vụ',
        domain=[('type', '=', 'service')],
        ondelete='restrict',
    )
    appointment_date = fields.Date(string='Ngày hẹn', required=True)
    appointment_timezone = fields.Char(
        default=lambda self: self.env.user.tz or 'UTC',
        required=True,
        readonly=True,
    )
    start_time = fields.Float(string='Giờ bắt đầu')
    end_time = fields.Float(string='Giờ kết thúc dự kiến')
    calendar_start = fields.Datetime(
        string='Bắt đầu',
        compute='_compute_calendar_times',
        store=True,
    )
    calendar_end = fields.Datetime(
        string='Kết thúc',
        compute='_compute_calendar_times',
        store=True,
    )
    guest_count = fields.Integer(string='Số lượng khách', required=True, default=1)
    status = fields.Selection([
        ('draft', 'Nháp'),
        ('confirmed', 'Đã xác nhận'),
        ('checked_in', 'Đã đến'),
        ('in_progress', 'Đang thực hiện'),
        ('done', 'Hoàn thành'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái lịch hẹn', required=True, default='draft')
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Hóa đơn',
        readonly=True,
        copy=False,
        ondelete='restrict',
        domain=[('move_type', '=', 'out_invoice')],
    )
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state',
        string='Trạng thái thanh toán',
        readonly=True,
    )
    note = fields.Text(string='Ghi chú')

    appointment_line_ids = fields.One2many(
        'spa.appointment.line',
        'appointment_id',
        string='Dịch vụ đã chọn',
        copy=True,
    )
    service_duration_minutes = fields.Integer(
        string='Tổng thời lượng dịch vụ (phút)',
        compute='_compute_service_duration',
        store=True,
    )
    service_summary = fields.Char(
        string='Dịch vụ / combo',
        compute='_compute_service_summary',
    )

    @api.depends(
        'customer_id.name',
        'service_product_id.name',
        'appointment_line_ids.product_id.name',
    )
    def _compute_name(self):
        for appointment in self:
            parts = [appointment.customer_id.name or 'Lịch hẹn']
            services = appointment.appointment_line_ids.mapped('product_id.name')
            if services:
                parts.extend(services)
            elif appointment.service_product_id:
                parts.append(appointment.service_product_id.name)
            appointment.name = ' - '.join(parts)

    @api.depends('appointment_line_ids.duration_minutes')
    def _compute_service_duration(self):
        for appointment in self:
            appointment.service_duration_minutes = sum(
                appointment.appointment_line_ids.mapped('duration_minutes')
            )

    @api.depends(
        'appointment_line_ids.product_id.name',
        'appointment_line_ids.combo_choice_ids.combo_item_id.product_id.name',
        'service_product_id.name',
        'service_id.name',
    )
    def _compute_service_summary(self):
        for appointment in self:
            services = []
            for line in appointment.appointment_line_ids:
                name = line.product_id.name
                if line.product_id.type == 'combo':
                    components = line.combo_choice_ids.mapped(
                        'combo_item_id.product_id.name'
                    )
                    if components:
                        name = f"{name} ({', '.join(components)})"
                services.append(name)
            if not services and appointment.service_product_id:
                services.append(appointment.service_product_id.name)
            if not services and appointment.service_id:
                services.append(appointment.service_id.name)
            appointment.service_summary = ', '.join(services)

    @api.onchange('appointment_line_ids', 'start_time')
    def _onchange_appointment_services(self):
        for appointment in self:
            duration = appointment.service_duration_minutes
            if duration and appointment.start_time is not False:
                appointment.end_time = (
                    appointment.start_time * 60 + duration
                ) / 60
        self._clear_unavailable_resources()

    @api.depends('appointment_date', 'start_time', 'end_time')
    def _compute_available_resources(self):
        room_model = self.env['spa.room']
        bed_model = self.env['spa.bed']
        for appointment in self:
            active_rooms = room_model.search([('active', '=', True)])
            active_beds = bed_model.search([
                ('active', '=', True),
                ('room_id', 'in', active_rooms.ids),
            ])
            occupied_bed_ids = set()
            if (
                not appointment.appointment_date
                or appointment.start_time is False
                or appointment.end_time is False
                or appointment.end_time <= appointment.start_time
            ):
                available_beds = active_beds
            else:
                overlapping_domain = [
                    ('appointment_date', '=', appointment.appointment_date),
                    ('status', 'not in', ('cancelled', 'done')),
                    ('start_time', '<', appointment.end_time),
                    ('end_time', '>', appointment.start_time),
                ]
                if appointment._origin.id:
                    overlapping_domain.append(('id', '!=', appointment._origin.id))
                occupied_beds = self.search(overlapping_domain).mapped('bed_id')
                occupied_bed_ids = set(occupied_beds.ids)
                available_beds = active_beds - occupied_beds
            appointment.available_bed_ids = available_beds
            available_room_ids = set(available_beds.mapped('room_id').ids)
            appointment.available_room_ids = active_rooms.filtered(
                lambda room: room.id in available_room_ids
            )
            appointment.resource_grid = [
                {
                    'id': room.id,
                    'name': room.display_name,
                    'available': room.id in available_room_ids,
                    'beds': [
                        {
                            'id': bed.id,
                            'name': bed.display_name,
                            'available': bed.id not in occupied_bed_ids,
                        }
                        for bed in active_beds.filtered(
                            lambda bed: bed.room_id == room
                        )
                    ],
                }
                for room in active_rooms
            ]

    @api.onchange('appointment_date', 'start_time', 'end_time')
    def _onchange_resource_availability(self):
        self._clear_unavailable_resources()

    def _clear_unavailable_resources(self):
        for appointment in self:
            if (
                appointment.room_id
                and appointment.room_id not in appointment.available_room_ids
            ):
                appointment.room_id = False
                appointment.bed_id = False
            elif (
                appointment.bed_id
                and appointment.bed_id not in appointment.available_bed_ids
            ):
                appointment.bed_id = False

    @api.onchange('room_id')
    def _onchange_room_id(self):
        if self.bed_id and self.bed_id.room_id != self.room_id:
            self.bed_id = False

    @api.onchange('customer_phone')
    def _onchange_customer_phone(self):
        for appointment in self:
            phone = re.sub(r'\D', '', appointment.customer_phone or '')
            appointment.customer_id = False
            if len(phone) != 10:
                continue

            phone_suffix = phone[-6:]
            candidates = self.env['res.partner'].with_context(
                active_test=False
            ).search([
                '|',
                ('phone', 'ilike', phone_suffix),
                ('mobile', 'ilike', phone_suffix),
            ], limit=100)
            matching_customers = candidates.filtered(
                lambda partner: any(
                    re.sub(r'\D', '', number or '') == phone
                    for number in (partner.phone, partner.mobile)
                )
            )
            if len(matching_customers) == 1:
                customer = matching_customers
                appointment.customer_id = customer
                return {
                    'warning': {
                        'title': 'Đã tìm thấy khách hàng',
                        'message': (
                            f'Đã tìm thấy hồ sơ CRM "{customer.display_name}" '
                            'và tự động chọn khách hàng này.'
                        ),
                        'type': 'notification',
                    },
                }
            if len(matching_customers) > 1:
                return {
                    'warning': {
                        'title': 'Có nhiều khách hàng trùng số điện thoại',
                        'message': (
                            'Vui lòng chọn đúng khách hàng CRM trong trường '
                            '"Khách hàng".'
                        ),
                        'type': 'notification',
                    },
                }
            return {
                'warning': {
                    'title': 'Chưa có hồ sơ khách hàng',
                    'message': (
                        'Không tìm thấy khách hàng CRM với số điện thoại này. '
                        'Hãy tạo hoặc chọn hồ sơ khách hàng trước khi lưu lịch hẹn.'
                    ),
                    'type': 'notification',
                },
            }

    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        for appointment in self:
            if appointment.customer_id:
                customer_phone = (
                    appointment.customer_id.phone
                    or appointment.customer_id.mobile
                )
                if customer_phone:
                    appointment.customer_phone = customer_phone

    def action_confirm(self):
        self.ensure_one()
        if self.status != 'draft':
            raise ValidationError('Chỉ lịch nháp mới có thể xác nhận.')
        self.status = 'confirmed'

    def action_check_in(self):
        self.ensure_one()
        if self.status != 'confirmed':
            raise ValidationError('Chỉ lịch đã xác nhận mới có thể chuyển sang Đã đến.')
        self.status = 'checked_in'

    def action_start(self):
        self.ensure_one()
        if self.status != 'checked_in':
            raise ValidationError('Chỉ khách đã đến mới có thể bắt đầu thực hiện dịch vụ.')
        self.status = 'in_progress'

    def action_done(self):
        self.ensure_one()
        if not self.env.user.has_group('spa.group_spa_billing_user'):
            raise AccessError(
                'Bạn cần quyền Spa Billing User để hoàn tất dịch vụ và lập hóa đơn.'
            )
        if self.status != 'in_progress':
            raise ValidationError('Chỉ dịch vụ đang thực hiện mới có thể hoàn thành.')
        order_lines = []
        combo_selections = []
        if self.appointment_line_ids:
            for index, line in enumerate(self.appointment_line_ids):
                description = line.product_id.name
                components = line.combo_choice_ids.mapped(
                    'combo_item_id.product_id.product_tmpl_id.name'
                )
                if components:
                    description = f"{description} ({', '.join(components)})"
                order_lines.append(
                    self._prepare_order_line(
                        line.product_id, description, sequence=(index + 1) * 10
                    )
                )
                if line.product_id.type == 'combo':
                    combo_choices = line.combo_choice_ids.sorted(
                        key=lambda choice: line.product_id.combo_ids.ids.index(
                            choice.combo_id.id
                        )
                    )
                    combo_selections.append((
                        (index + 1) * 10,
                        [{
                            'product_id': choice.combo_item_id.product_id.id,
                            'combo_item_id': choice.combo_item_id.id,
                            'no_variant_attribute_value_ids': [],
                            'product_custom_attribute_values': [],
                        } for choice in combo_choices],
                    ))
        elif self.service_product_id:
            order_lines.append(
                self._prepare_order_line(self.service_product_id)
            )
        elif self.service_id:
            products = self.env['product.template'].search([
                ('name', '=', self.service_id.name),
                ('type', '=', 'service'),
            ], limit=2)
            if len(products) != 1:
                raise ValidationError(
                    'Không thể lập hóa đơn cho dịch vụ cũ này. '
                    'Hãy liên kết dịch vụ với một sản phẩm dịch vụ Spa.'
                )
            order_lines.append(self._prepare_order_line(products))

        if not order_lines:
            raise ValidationError('Không có dịch vụ để tạo đơn hàng.')

        order = self.env['sale.order'].create({
            'partner_id': self.customer_id.id,
            'origin': self.name,
            'spa_appointment_id': self.id,
            'order_line': [
                fields.Command.create(line_vals) for line_vals in order_lines
            ],
        })
        for sequence, selected_items in combo_selections:
            order_line = order.order_line.filtered(
                lambda line: line.sequence == sequence and line.product_type == 'combo'
            )
            order_line.selected_combo_items = json.dumps(selected_items)
        if combo_selections:
            order._onchange_order_line()
        order.order_line.filtered(
            lambda line: not line.display_type
        ).write({'qty_delivered': 1})
        self.write({
            'status': 'done',
            'sale_order_id': order.id,
        })
        return self.action_open_sale_order()

    def _award_loyalty_points(self):
        self.ensure_one()
        invoice = self.invoice_id
        if (
            not invoice
            or invoice.state != 'posted'
            or invoice.payment_state != 'paid'
        ):
            return

        transaction_model = self.env['customer.loyalty.transaction'].sudo()
        existing_transaction = transaction_model.search(
            [('appointment_id', '=', self.id)],
            limit=1,
        )
        if existing_transaction:
            return existing_transaction

        vnd_currency = self.env.ref('base.VND')
        amount_vnd = invoice.currency_id._convert(
            invoice.amount_total,
            vnd_currency,
            invoice.company_id,
            fields.Date.context_today(self),
        )
        points = int(amount_vnd / 10_000)
        if points <= 0:
            return

        transaction = transaction_model.create({
            'name': f'Tích điểm từ lịch hẹn {self.display_name}',
            'partner_id': self.customer_id.id,
            'appointment_id': self.id,
            'date': fields.Date.context_today(self),
            'transaction_type': 'earn',
            'points': points,
            'note': (
                f'Tự động cộng {points} điểm từ tổng chi tiêu '
                f'{vnd_currency.round(amount_vnd):,.0f} VND.'
            ),
        })
        transaction.action_apply_points()

    def _prepare_order_line(self, product, description=None, sequence=10):
        values = {
            'product_id': product.product_variant_id.id,
            'name': description or product.name,
            'product_uom_qty': 1,
            'price_unit': product.list_price,
            'sequence': sequence,
        }
        return values

    def action_open_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            raise ValidationError('Lịch hẹn này chưa có đơn hàng.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đơn hàng Spa',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
            'target': 'current',
        }

    def action_open_invoice(self):
        self.ensure_one()
        if not self.env.user.has_group('spa.group_spa_billing_user'):
            raise AccessError(
                'Bạn cần quyền Spa Billing User để xem hóa đơn và ghi nhận thanh toán.'
            )
        if not self.invoice_id:
            raise ValidationError('Lịch hẹn này chưa có hóa đơn.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn thanh toán',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
            'target': 'current',
        }

    def action_cancel(self):
        self.ensure_one()
        if self.status in ('done', 'cancelled'):
            raise ValidationError('Lịch đã hoàn thành hoặc đã hủy, không thể hủy thêm.')
        self.status = 'cancelled'

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get([
            'employee_id', 'room_id', 'bed_id', 'start_time', 'end_time',
        ])
        for vals in vals_list:
            if not vals.get('employee_id', defaults.get('employee_id')):
                raise ValidationError('Vui lòng chọn nhân viên phụ trách.')
            if not vals.get('room_id', defaults.get('room_id')):
                raise ValidationError('Vui lòng chọn phòng Spa.')
            if not vals.get('bed_id', defaults.get('bed_id')):
                raise ValidationError('Vui lòng chọn giường Spa.')
            if vals.get('start_time', defaults.get('start_time')) is False:
                raise ValidationError('Vui lòng chọn giờ bắt đầu.')
            if vals.get('end_time', defaults.get('end_time')) is False:
                raise ValidationError('Vui lòng chọn giờ kết thúc.')
        return super().create(vals_list)

    @api.depends('appointment_date', 'appointment_timezone', 'start_time', 'end_time')
    def _compute_calendar_times(self):
        for appointment in self:
            if (
                appointment.appointment_date
                and appointment.start_time is not False
                and appointment.end_time is not False
            ):
                date = fields.Date.to_date(appointment.appointment_date)
                local_midnight = datetime.combine(date, time.min)
                local_start = local_midnight + timedelta(hours=appointment.start_time)
                local_end = local_midnight + timedelta(hours=appointment.end_time)
                timezone = pytz.timezone(appointment.appointment_timezone or 'UTC')
                appointment.calendar_start = timezone.localize(
                    local_start
                ).astimezone(pytz.UTC).replace(tzinfo=None)
                appointment.calendar_end = timezone.localize(
                    local_end
                ).astimezone(pytz.UTC).replace(tzinfo=None)
            else:
                appointment.calendar_start = False
                appointment.calendar_end = False

    @api.constrains('customer_phone')
    def _check_customer_phone(self):
        for appointment in self:
            phone = re.sub(r'\D', '', appointment.customer_phone or '')
            if not re.fullmatch(r'[0-9]{10}', phone):
                raise ValidationError('Số điện thoại phải gồm đúng 10 chữ số.')

    @api.constrains(
        'appointment_date', 'guest_count', 'start_time', 'end_time',
        'employee_id', 'room_id', 'bed_id', 'status',
        'service_id', 'service_product_id', 'appointment_line_ids',
    )
    def _check_appointment_values(self):
        for appointment in self:
            if (
                not appointment.service_id
                and not appointment.service_product_id
                and not appointment.appointment_line_ids
            ):
                raise ValidationError('Vui lòng chọn ít nhất một dịch vụ hoặc combo.')
            if not appointment.employee_id or not appointment.room_id or not appointment.bed_id:
                raise ValidationError(
                    'Vui lòng chọn nhân viên phụ trách, phòng và giường Spa.'
                )
            if appointment.bed_id.room_id != appointment.room_id:
                raise ValidationError('Giường được chọn không thuộc phòng đã chọn.')
            if appointment.guest_count < 1:
                raise ValidationError('Số lượng khách phải lớn hơn 0.')
            if appointment.appointment_date < fields.Date.context_today(appointment):
                raise ValidationError('Ngày hẹn không được là ngày trong quá khứ.')
            if not 0 <= appointment.start_time < 24 or not 0 <= appointment.end_time < 24:
                raise ValidationError('Giờ hẹn phải nằm trong khoảng từ 00:00 đến trước 24:00.')
            if appointment.end_time <= appointment.start_time:
                raise ValidationError('Giờ kết thúc phải sau giờ bắt đầu.')
            if (
                appointment.service_duration_minutes
                and appointment.end_time * 60
                < appointment.start_time * 60 + appointment.service_duration_minutes
            ):
                raise ValidationError(
                    'Thời gian kết thúc phải đủ cho tổng thời lượng các dịch vụ đã chọn.'
                )
            if appointment.status in ('cancelled', 'done'):
                continue

            overlapping_appointment = self.search([
                ('id', '!=', appointment.id),
                ('appointment_date', '=', appointment.appointment_date),
                ('status', 'not in', ('cancelled', 'done')),
                ('start_time', '<', appointment.end_time),
                ('end_time', '>', appointment.start_time),
                '|',
                ('employee_id', '=', appointment.employee_id.id),
                ('bed_id', '=', appointment.bed_id.id),
            ], limit=1)
            if overlapping_appointment:
                raise ValidationError(
                    'Nhân viên hoặc giường đã có lịch hẹn trong khoảng thời gian này.'
                )
