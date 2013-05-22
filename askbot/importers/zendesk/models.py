import re
from django.db import models
from django.contrib.auth.models import User as DjangoUser
from django.utils.html import strip_tags
from askbot.utils.html import unescape

TAGS = {}#internal cache for mappings forum id _> forum name

class Entry(models.Model):
    """
    Top level topic posts in a forum
    """
    body = models.TextField()
    created_at = models.DateTimeField()
    tags = models.CharField(max_length = 255, null = True)
    flag_type_id = models.IntegerField() # topic type
    forum_id = models.IntegerField() # forum entry is in
    hits = models.IntegerField(null = True) # number of views
    entry_id = models.IntegerField()
    is_highlighted = models.BooleanField(default = False) # ignored
    is_locked = models.BooleanField(default = False) # close
    is_pinned = models.BooleanField(default = False) # ignored
    is_public = models.BooleanField(default = True)
    organization_id = models.IntegerField(null = True)
    position = models.IntegerField(null = True) # ignored
    posts_count = models.IntegerField(null = True)
    submitter_id = models.IntegerField()
    title = models.CharField(max_length = 300)
    updated_at = models.DateTimeField()
    votes_count = models.IntegerField(null = True, default = 0)
    ab_id = models.IntegerField(null = True)

    def get_author(self):
        """returns author of the post, from the Django user table"""
        zendesk_user = User.objects.get(user_id = self.submitter_id)
        return DjangoUser.objects.get(id = zendesk_user.askbot_user_id)

    def get_body_text(self):
        """unescapes html entities in the body text,
        saves in the internal cache and returns the value"""
        if not hasattr(self, '_body_text'):
            self._body_text = unescape(self.body)
        return self._body_text

    def get_tag_names(self):
        """return tags on entry as well as forum title as a tag"""
        if self.forum_id not in TAGS:
            forum = Forum.objects.get(forum_id = self.forum_id)
            tag_name = re.sub(r'\s+', '_', forum.name.lower())
            TAGS[self.forum_id] = tag_name
        tags = TAGS[self.forum_id]
        if self.tags:
            tags += " %s" % self.tags
        return tags

class Post(models.Model):
    """
    comments on an Entry in a Forum
    """
    body = models.TextField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    entry_id = models.IntegerField()
    post_id = models.IntegerField()
    forum_id = models.IntegerField()
    user_id = models.IntegerField()
    is_informative = models.BooleanField()
    ab_id = models.IntegerField(null = True)

    def get_author(self):
        """returns author of the post, from the Django user table"""
        zendesk_user = User.objects.get(user_id = self.user_id)
        return DjangoUser.objects.get(id = zendesk_user.askbot_user_id)

    def get_body_text(self):
        """unescapes html entities in the body text,
        saves in the internal cache and returns the value"""
        if not hasattr(self, '_body_text'):
            self._body_text = unescape(self.body)
        return self._body_text

class User(models.Model):
    user_id = models.IntegerField()
    askbot_user_id = models.IntegerField(null = True)
    created_at = models.DateTimeField()
    is_active = models.BooleanField()
    last_login = models.DateTimeField(null = True)
    name = models.CharField(max_length = 255)
    openid_url = models.URLField(null = True)
    organization_id = models.IntegerField(null = True)
    phone = models.CharField(max_length = 32, null = True)
    restriction_id = models.IntegerField()
    roles = models.IntegerField()
    time_zone = models.CharField(max_length = 255)
    updated_at = models.DateTimeField()
    uses_12_hour_clock = models.BooleanField()
    email = models.EmailField(null = True)
    is_verified = models.BooleanField()
    photo_url = models.URLField()

class Forum(models.Model):
    description = models.CharField(max_length = 255, null = True)
    display_type_id = models.IntegerField()
    entries_count = models.IntegerField()
    forum_id = models.IntegerField()
    is_locked = models.BooleanField()
    name = models.CharField(max_length = 255)
    organization_id = models.IntegerField(null = True)
    position = models.IntegerField(null = True)
    updated_at = models.DateTimeField()
    translation_locale_id = models.IntegerField(null = True)
    use_for_suggestions = models.BooleanField()
    visibility_restriction_id = models.IntegerField()
    is_public = models.BooleanField()

class Ticket(models.Model):
    assigned_at = models.DateTimeField()
    assignee_id = models.IntegerField()
    base_score = models.IntegerField()
    created_at = models.DateTimeField()
    current_collaborators nil="true"></current_collaborators>
    current_tags nil="true"></current_tags>
    description = models.CharField()
    due_date = models.DateTimeField()
    entry_id = models.IntegerField(null = True)
    external_id = models.IntegerField(null = True)
    group_id = models.IntegerField(null = True)
    initially_assigned_at = models.DateTimeField()
    latest_recipients = models.CharField(null = True)
    nice_id = models.IntegerField()
    organization_id = models.IntegerField(null = True)
    original_recipient_address = models.CharField(max_length = 255, null = True)
    priority_id = models.IntegerField()
    recipient = models.CharField(max_length = 255)
    requester_id = models.IntegerField()
    resolution_time = models.IntegerField(null = True)
    solved_at = models.DateTimeField()
    status_id = models.IntegerField()
    status_updated_at = models.DateTimeField()
    subject = models.CharField(max_length = 255)
    submitter_id = models.IntegerField()
    ticket_type_id = models.IntegerField()
    updated_at = models.DateTimeField()
    updated_by_type_id = models.IntegerField(null = True)
    via_id = models.IntegerField()
    score = models.IntegerField()
    problem_id = models.IntegerField(null = True)
    has_incidents = models.BooleanField(default = False)

class Comment(models.Model):
    """todo: attachments and custom fields"""
    author_id = models.IntegerField()
    created_at type="datetime">2009_04_03T16:15:27+01:00</created_at>
    is_public = models.BooleanField(default = True)
    type = models.CharField(max_length = 255)
    value = models.CharField()
    via_id = models.IntegerField()
 
