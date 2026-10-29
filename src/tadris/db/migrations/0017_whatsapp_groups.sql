-- WhatsApp groups. Tadris cannot create a WhatsApp group (no account, no API): the desk
-- creates it in WhatsApp once and pastes its invite link on the Tadris group. Announcements
-- then go to the WhatsApp group in one send instead of one chat per parent.

-- The invite code of the linked WhatsApp group (https://chat.whatsapp.com/<code>); NULL: none.
ALTER TABLE class_groups ADD COLUMN whatsapp_code TEXT;

-- The parents whose chat was opened with the invitation, so that the desk invites only the
-- ones left (a new student's parents). Cleared when the group gets another link: the old
-- one may have been revoked.
CREATE TABLE whatsapp_invites (
  group_id   INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE RESTRICT,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
  invited_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
  PRIMARY KEY (group_id, contact_id)
);
