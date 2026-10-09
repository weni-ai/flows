class ChannelMigrationError(Exception):
    """Base error for channel migration use case."""


class ChannelNotFoundError(ChannelMigrationError):
    def __init__(self, channel_uuid):
        super().__init__(f"Channel not found: {channel_uuid}")
        self.channel_uuid = channel_uuid


class DestOrgNotFoundError(ChannelMigrationError):
    def __init__(self, project_uuid):
        super().__init__(f"Destination org not found for project: {project_uuid}")
        self.project_uuid = project_uuid


class ChannelWithoutOrgError(ChannelMigrationError):
    def __init__(self, channel_uuid):
        super().__init__(f"Channel has no org: {channel_uuid}")
        self.channel_uuid = channel_uuid


class ChannelOrgMismatchError(ChannelMigrationError):
    def __init__(self, channel_uuid, expected_project_uuid, actual_project_uuid):
        super().__init__(
            f"Channel {channel_uuid} belongs to project {actual_project_uuid}, " f"expected {expected_project_uuid}"
        )
        self.channel_uuid = channel_uuid
        self.expected_project_uuid = expected_project_uuid
        self.actual_project_uuid = actual_project_uuid
