/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class SpaResourceGrid extends Component {
    static template = "spa.ResourceGrid";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({
            rooms: [],
            selectedRoomId: false,
            selectedBedId: false,
        });
        useRecordObserver((record) => {
            this.state.rooms = record.data[this.props.name] || [];
            this.state.selectedRoomId = record.data.room_id?.[0] || false;
            this.state.selectedBedId = record.data.bed_id?.[0] || false;
        });
    }

    get rooms() {
        return this.state.rooms;
    }

    get selectedRoomId() {
        return this.state.selectedRoomId;
    }

    get selectedBedId() {
        return this.state.selectedBedId;
    }

    async selectBed(room, bed) {
        if (this.props.readonly || !bed.available) {
            return;
        }
        await this.props.record.update({
            room_id: [room.id, room.name],
            bed_id: [bed.id, bed.name],
        });
    }
}

registry.category("fields").add("spa_resource_grid", {
    component: SpaResourceGrid,
    supportedTypes: ["json"],
});
