"""importer from zendesk data dump
the dump must be a tar/gzipped file, containing one directory
with all the .xml files.

Run this command as::

    python manage.py import_zendesk path/to/dump.tgz
"""
import os
import re
import sys
import tarfile
import tempfile
from datetime import datetime, date
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from lxml import etree
from askbot import models as askbot_models
from askbot.utils import console
from askbot.utils.html import unescape

from askbot.importers.zendesk import models as zendesk_models

#a hack, did not know how to parse timezone offset
ZERO_TIME = datetime.strptime('00:00', '%H:%M')
# load admin user for user where needed (eg. user who closed thread)
ADMIN_USER = askbot_models.User.objects.filter(is_superuser=True)[:1]

def get_unique_username(name_seed):
    """returns unique user name, by modifying the
    name if the same name exists in the database
    until the modified name is unique
    """
    original_name = name_seed
    attempt_no = 1
    while True:
        try:
            askbot_models.User.objects.get(username = name_seed)
            name_seed = original_name + str(attempt_no)
            attempt_no += 1
        except askbot_models.User.DoesNotExist:
            return name_seed

# def clean_username(name_seed):
#     """makes sure that the name is unique
#     and is no longer than 30 characters"""
#     username = get_unique_username(name_seed)
#     if len(username) > 30:
#         username = get_unique_username(username[:28])
#         if len(username) > 30:
#             #will allow about a million extra possible unique names
#             username = get_unique_username(username[:24])
#     return username

def create_askbot_user(zd_user):
    """create askbot user from zendesk user record
    return askbot user or None, if there is error
    """
    #special treatment for the user name
    # raw_username = unescape(zd_user.name)
    #username = clean_username(raw_username)
    # if len(username) > 30:#nearly impossible skip such user
    #     print "Warning: could not import user %s" % raw_username
    #     return None

    if zd_user.email is None:
        email = ''
        username = zd_user.name.replace(" ", "_").lower()
    else:
        email = zd_user.email
        # temporary invalidate emails so we don't spam people by accident
        if not email.endswith('shotgunsoftware.com'):
            email = "%s@example.com" % email.split('@')[0]
        username = zd_user.email
    username = get_unique_username(username)

    ab_user = askbot_models.User(
        email = email,
        email_isvalid = zd_user.is_verified,
        date_joined = zd_user.created_at,
        last_seen = zd_user.created_at,#add initial date for now
        username = username,
        is_active = zd_user.is_active
    )
    ab_user.save()
    return ab_user

def post_question(zendesk_entry):
    """posts question to askbot, using zendesk entry"""
    try:
        askbot_post = zendesk_entry.get_author().post_question(
            title = zendesk_entry.title,
            body_text = zendesk_entry.get_body_text(),
            tags = zendesk_entry.get_tag_names(),
            timestamp = zendesk_entry.created_at
        )
        # seed the views with the # hits we had on zendesk
        askbot_post.thread.increase_view_count(increment=zendesk_entry.hits)
        # UNIMPLEMENTED: seed the votes with the # votes we had on zendesk
        # askbot_post.thread.increase_vote_count(increment=zendesk_entry.votes_count)
        # close threads that were locked in Zendesk and assign a default
        # reason of "question answered". Set default user to admin.
        if zendesk_entry.is_locked:
            askbot_post.thread.set_closed_status(
                closed=True, 
                closed_by=ADMIN_USER, 
                closed_at=datetime.now(), 
                close_reason=5)
        askbot_post.thread.save()
        return askbot_post
    except Exception, e:
        msg = unicode(e)
        print "Warning: entry %d dropped: %s" % (zendesk_entry.entry_id, msg)

def post_answer(zendesk_post, question = None):
    """posts answer to askbot, using zendesk post"""
    try:
        askbot_post = zendesk_post.get_author().post_answer(
            question = question,
            body_text = zendesk_post.get_body_text(),
            timestamp = zendesk_post.created_at
        )
        # mark answer as accepted if it's been marked as an answer in Zendesk
        # Zendesk supports multiple answers so this will re-mark the answer
        # for each one and ultimately end on the most recent post.
        if zendesk_post.is_informative:
            askbot_post.thread.accepted_answer_id = askbot_post.id
            askbot_post.thread.save()
        return askbot_post
    except Exception, e:
        msg = unicode(e)
        print "Warning: post %d dropped: %s" % (zendesk_post.post_id, msg)

def get_val(elem, field_name):
    field = elem.find(field_name)
    if field is None:
        return None
    try:
        field_type = field.attrib['type']
    except KeyError:
        field_type = ''
    raw_val = field.text
    if raw_val is None:
        return None

    if field_type == 'boolean':
        if raw_val == 'true':
            return True
        elif raw_val == 'false':
            return False
        else:
            raise ValueError('"true" or "false" expected, found "%s"' % raw_val)
    elif field_type.endswith('integer'):
        return int(raw_val)
    elif field_type == 'datetime':
        if raw_val is None:
            return None
        raw_datetime = raw_val[:19]
        tzoffset_sign = raw_val[19]
        raw_tzoffset = raw_val[20:]
        if raw_val:
            dt = datetime.strptime(raw_datetime, '%Y-%m-%dT%H:%M:%S')
            tzoffset_amt = datetime.strptime(raw_tzoffset, '%H:%M')
            tzoffset = tzoffset_amt - ZERO_TIME
            if tzoffset_sign == '-':
                return dt - tzoffset
            else:
                return dt + tzoffset
        else:
            return None
    else:
        return raw_val

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        if len(args) != 1:
            raise CommandError('please provide path to tarred and gzipped cnprog dump')

        self.tar = tarfile.open(args[0], 'r:gz')

        # read in all of the data to import and store it in our temporary
        # tables.
        sys.stdout.write('Reading users.xml: ')
        self.read_users()
        sys.stdout.write('Reading forums.xml: ')
        self.read_forums()
        sys.stdout.write('Reading entries.xml: ')
        self.read_entries()
        sys.stdout.write('Reading posts.xml: ')
        self.read_posts()
        # sys.stdout.write('Reading tickets.xml: ')
        # self.read_tickets()

        # start importing data from the temp zendesk_* tables into the askbot
        # tables
        # users
        sys.stdout.write("Importing user accounts: ")
        self.import_users()
        
        # forums
        forum_ids = []
        for forum in zendesk_models.Forum.objects.all():
            if not forum.viewable_to_public():
                console.print_action("skipping non-public forum \"%s\"" % forum.name, nowipe=True)
                continue
            if console.get_yes_or_no("Import forum \"%s\" ?" % forum.name) == 'yes':
                forum_ids.append(forum.forum_id)
        sys.stdout.write("Loading forum threads: ")
        self.import_forum(forum_ids=forum_ids)

    def get_file(self, file_name):
        first_item = self.tar.getnames()[0]
        file_path = file_name
        if not first_item.endswith('.xml'):
            file_path = os.path.join(first_item, file_path)
            
        file_info = self.tar.getmember(file_path)
        xml_file = self.tar.extractfile(file_info)
        return etree.parse(xml_file)

    @transaction.autocommit
    def read_xml_file(self,
            file_name = None,
            entry_name = None,
            model = None,
            fields = None,
            extra_field_mappings = None,
            sub_entities = None
        ):
        """
        * file_name - is name of xml file,
        * entry_name - name of entries to read from the xml file
        * model - model, which is to receive data
        * fields - list of field names in xml that will be translated to model fields
                   by simple substitiution of '-' with '_'
        * extra field mappings - list of two tuples where xml field names are
          translated to model fields in a special way
        * sub_entities - list of fields that should be treated as separate
                    models (like Ticket.comments)
                    [{'comments': (
                        'comment', 
                        zendesk_models.Comment, 
                        ['author-id', 'created-at', 'is-public', 'type', 
                            'value', 'via-id', 'ticket-id'], 
                        None,
                        None)
                    }]
        """
        xml = self.get_file(file_name)
        items_saved = 0
        for xml_entry in xml.findall(entry_name):
            instance = model()
            for field in fields:
                value = get_val(xml_entry, field)
                model_field_name = field.replace('-', '_')
                max_length = instance._meta.get_field(model_field_name).max_length
                if value and max_length:
                    value = value[:max_length]
                setattr(instance, model_field_name, value)
            if extra_field_mappings:
                for (field, model_field_name) in extra_field_mappings:
                    value = get_val(xml_entry, field)
                    setattr(instance, model_field_name, value)

            # if sub_entities:
            #     # {}
            #     for sub_entity in sub_entities:
            #         # 'comments', ()
            #         for sub_field_name, sub_def in sub_entity:
            #             # 'comment', zendesk_models.Comment, ['author-id', ...], None, None
            #             sub_entry_name, sub_model, sub_fields, sub_extra_field_mappings, _ = sub_def
            #             # <#zendesk_models.Comment>
            #             sub_instance = sub_model()
            #             # 'author_id' in ['author-id', ...]
            #             for sub_field in sub_fields:
            #                 # 1234567
            #                 sub_value = get_val(xml_entry, sub_field)
            #                 sub_model_field_name = sub_field.replace('-', '_')
            #                 sub_max_length = sub_instance._meta.get_field(sub_model_field_name).max_length
            #                 if sub_value and sub_max_length:
            #                     sub_value = sub_value[:sub_max_length]

            instance.save()
            items_saved += 1
            console.print_action('%d items' % items_saved)
        console.print_action('%d items' % items_saved, nowipe = True)


    def read_users(self):
        self.read_xml_file(
            file_name = 'users.xml',
            entry_name = 'user',
            model = zendesk_models.User,
            fields = (
                'created-at', 'is-active', 'last-login', 'name',
                'openid-url', 'organization-id', 'phone', 'restriction-id',
                'roles', 'time-zone', 'updated-at', 'uses-12-hour-clock',
                'email', 'is-verified', 'photo-url'
            ),
            extra_field_mappings = (('id', 'user_id'),)
        )

    def read_entries(self):
        self.read_xml_file(
            file_name = 'entries.xml',
            entry_name = 'entry',
            model = zendesk_models.Entry,
            fields = (
                'body', 'created-at', 'tags', 'flag-type-id', 'forum-id',
                'hits', 'entry-id', 'is-highlighted', 'is-locked', 'is-pinned',
                'is-public', 'organization-id', 'position', 'posts-count', 
                'submitter-id', 'title', 'updated-at', 'votes-count'
            ),
            extra_field_mappings = (
                ('id', 'entry_id'),
            )
        )

    def read_posts(self):
        self.read_xml_file(
            file_name = 'posts.xml',
            entry_name = 'post',
            model = zendesk_models.Post,
            fields = (
                'body', 'created-at', 'updated-at', 'entry-id',
                'forum-id', 'user-id', 'is-informative'
            ),
            extra_field_mappings = (
                ('id', 'post_id'),
            )
        )

    def read_forums(self):
        self.read_xml_file(
            file_name = 'forums.xml',
            entry_name = 'forum',
            model = zendesk_models.Forum,
            fields = (
                'description', 'display-type-id',
                'entries-count', 'is-locked',
                'name', 'organization-id',
                'position', 'updated-at',
                'translation-locale-id',
                'use-for-suggestions',
                'visibility-restriction-id',
                'is-public'
            ),
            extra_field_mappings = (('id', 'forum_id'),)
        )

    def read_tickets(self):
        """todo: add comments"""
        self.read_xml_file(
            file_name = 'tickets.xml',
            entry_name = 'ticket',
            model = zendesk_models.Ticket,
            fields = (
                'assigned-at', 'assignee-id', 'base-score', 'created-at', 
                'current-collaborators','current-tags','description', 
                'due-date', 'entry-id', 'external-id', 'group-id', 
                'initially-assigned-at', 'latest-recipients', 'nice-id', 
                'organization-id', 'original-recipient-address', 'priority-id', 
                'recipient', 'requester-id', 'resolution-time', 'solved-at', 
                'status-id', 'status-updated-at', 'subject', 'submitter-id', 
                'ticket-type-id', 'updated-at', 'updated-by-type-id', 'via-id', 
                'score', 'problem-id', 'has-incidents'
            ),
            extra_field_mappings = (('nice-id', 'ticket_id'),)
        )

    @transaction.autocommit
    def import_users(self):
        added_users = 0
        for zd_user in zendesk_models.User.objects.all():
            #a whole bunch of fields are actually dropped now
            #see what's available in users.xml meanings of some
            #values there is not clear

            #if email is blank, just create a new user
            if zd_user.email == '':
                ab_user = create_askbot_user(zd_user)
                if ab_user in None:
                    print 'Warning: could not create user %s ' % zd_user.name
                    continue
                console.print_action(ab_user.username)
            else:
            #else see if user with the same email already exists
            #and only create new askbot user if email is not yet in the
            #database
                try:
                    ab_user = askbot_models.User.objects.get(email = zd_user.email)
                except askbot_models.User.DoesNotExist:
                    ab_user = create_askbot_user(zd_user)
                    if ab_user is None:
                        continue
                    console.print_action(ab_user.username, nowipe = True)
                    added_users += 1
            zd_user.askbot_user_id = ab_user.id
            zd_user.save()

            if zd_user.openid_url != None and \
                'askbot.deps.django_authopenid' in settings.INSTALLED_APPS:
                from askbot.deps.django_authopenid.models import UserAssociation
                from askbot.deps.django_authopenid.util import get_provider_name
                try:
                    assoc = UserAssociation(
                        user = ab_user,
                        openid_url = zd_user.openid_url,
                        provider_name = get_provider_name(zd_user.openid_url)
                    )
                    assoc.save()
                except:
                    #drop user association
                    pass

        console.print_action('%d users added' % added_users, nowipe = True)

    @transaction.autocommit
    def import_posts(self, question, entry):
        # followup posts on a forum topic
        for post in zendesk_models.Post.objects.filter(
                        entry_id=entry.entry_id
                        ).order_by('created_at'):
            # create answers
            answer = post_answer(post, question=question)
            if not answer:
                continue
            post.ab_id = answer.id
            post.save()

    @transaction.autocommit
    def import_entry(self, entry):
        # top-level forum topics
        question = post_question(entry)
        if not question:
            return
        entry.ab_id = question.id
        entry.save()
        self.import_posts(question, entry)
        #console.print_action(question.title)
        return True

    def import_forum(self, forum_ids):
        forums = zendesk_models.Forum.objects.filter(forum_id__in=forum_ids)
        for forum in forums:
            thread_count = 0
            # don't import private forums, forums restricted to organizations
            # or forums that require login (comment this out if you don't care,
            # or modify the viewable_to_public() method for zendesk_models.Forum)
            if not forum.viewable_to_public():
                console.print_action("skipping private forum \"%s\"" % forum.name, 
                                     nowipe = True)
                continue
            sys.stdout.write("Forum: %s... " % forum.name)
            for entry in zendesk_models.Entry.objects.filter(forum_id=forum.forum_id):
                if self.import_entry(entry):
                    thread_count += 1
                console.print_action(str(thread_count))
            console.print_action(str(thread_count), nowipe = True)


    # @transaction.commit_manually
    # def import_content(self):
    #     #[1, 3, 4]
    #     thread_ids = zendesk_models.Post.objects.values_list(
    #                                                     'entry_id',
    #                                                     flat = True
    #                                                 ).distinct()
    #     threads_posted = 0
    #     for thread_id in thread_ids:
    #         # [<Post #1>, <Post #3>, <Post #4]
    #         thread_entries = zendesk_models.Post.objects.filter(
    #             entry_id = thread_id
    #         ).order_by('created_at')
    #         question_post = thread_entries[0]
    #         question = post_question(question_post)
    #         question_post.is_processed = True
    #         question_post.save()
    #         transaction.commit()
    #         entry_count = thread_entries.count()
    #         threads_posted += 1
    #         console.print_action(str(threads_posted))
    #         if entry_count > 1:
    #             for answer_post in thread_entries[1:]:
    #                 post_answer(answer_post, question = question)
    #                 answer_post.is_processed = True
    #                 answer_post.save()
    #                 transaction.commit()
    #     console.print_action(str(threads_posted), nowipe = True)
