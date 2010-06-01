#todo: remove this with Django 1.2
from django.db import models
from django.contrib.contenttypes.models import ContentType
from forum.models import signals
from django.contrib.contenttypes import generic
from django.contrib.auth.models import User
from hashlib import md5
import string
from random import Random
from forum import const
from forum.utils import functions
import datetime
import logging

from django.utils.translation import ugettext as _

class ActivityManager(models.Manager):
    def get_all_origin_posts(self):
        #todo: redo this with query sets
        origin_posts = set()
        for m in self.all():
            post = m.content_object
            if post and hasattr(post, 'get_origin_post'):
                origin_posts.add(post.get_origin_post())
            else:
                logging.debug(
                            'method get_origin_post() not implemented for %s' \
                            % unicode(post)
                        )
        return list(origin_posts)

    def create_new_mention(
                self,
                mentioned_by = None,
                mentioned_whom = None,
                mentioned_at = None,
                mentioned_in = None,
                reported = None
            ): 

        #todo: automate this using python inspect module
        kwargs = dict()

        kwargs['activity_type'] = const.TYPE_ACTIVITY_MENTION

        if mentioned_at:
            #todo: handle cases with rich lookups here like __lt
            kwargs['active_at'] = mentioned_at

        if mentioned_by:
            kwargs['user'] = mentioned_by

        if mentioned_in:
            if functions.is_iterable(mentioned_in):
                raise NotImplementedError('mentioned_in only works for single items')
            else:
                post_content_type = ContentType.objects.get_for_model(mentioned_in)
                kwargs['content_type'] = post_content_type
                kwargs['object_id'] = mentioned_in.id

        if reported == True:
            kwargs['is_auditted'] = True
        else:
            kwargs['is_auditted'] = False

        mention_activity = Activity(**kwargs)
        mention_activity.save()

        if mentioned_whom:
            if functions.is_iterable(mentioned_whom):
                raise NotImplementedError('cannot yet mention multiple people at once')
            else:
                mention_activity.receiving_users.add(mentioned_whom)

        return mention_activity

    def get_mentions(
                self, 
                mentioned_by = None,
                mentioned_whom = None,
                mentioned_at = None,
                mentioned_in = None,
                reported = None
            ):

        kwargs = dict()

        kwargs['activity_type'] = const.TYPE_ACTIVITY_MENTION

        if mentioned_at:
            #todo: handle cases with rich lookups here like __lt
            kwargs['active_at'] = mentioned_at

        if mentioned_by:
            kwargs['user'] = mentioned_by

        if mentioned_whom:
            if functions.is_iterable(mentioned_whom):
                kwargs['receiving_users__in'] = mentioned_whom
            else:
                kwargs['receiving_users__in'] = (mentioned_whom,)

        if mentioned_in:
            if functions.is_iterable(mentioned_in):
                it = iter(mentioned_in)
                raise NotImplementedError('mentioned_in only works for single items')
            else:
                post_content_type = ContentType.objects.get_for_model(mentioned_in)
                kwargs['content_type'] = post_content_type
                kwargs['object_id'] = mentioned_in.id

        if reported == True:
            kwargs['is_auditted'] = True
        else:
            kwargs['is_auditted'] = False

        return self.filter(**kwargs)


class Activity(models.Model):
    """
    We keep some history data for user activities
    """
    user = models.ForeignKey(User)
    receiving_users = models.ManyToManyField(User, related_name='received_activity')
    activity_type = models.SmallIntegerField(choices = const.TYPE_ACTIVITY)
    active_at = models.DateTimeField(default=datetime.datetime.now)
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = generic.GenericForeignKey('content_type', 'object_id')
    is_auditted = models.BooleanField(default=False)

    objects = ActivityManager()

    def __unicode__(self):
        return u'[%s] was active at %s' % (self.user.username, self.active_at)

    class Meta:
        app_label = 'forum'
        db_table = u'activity'


class EmailFeedSettingManager(models.Manager):
    def exists_match_to_post_and_subscriber(
                                self,
                                post = None,
                                subscriber = None,
                                newly_mentioned_users = [],
                                **kwargs
                            ):
        """returns list of feeds matching the post
        and subscriber
        newly_mentioned_user parameter is there to save
        on a database hit looking for mentions of subscriber
        in the current post
        """
        feeds = self.filter(subscriber = subscriber, **kwargs)

        for feed in feeds:

            if feed.feed_type == 'm_and_c':
                if post.__class__.__name__ == 'Comment':#isinstance(post, Comment):
                    return True
                else:
                    if subscriber in newly_mentioned_users:
                        return True
            else:
                if feed.feed_type == 'q_all':
                    #'everything' category is tag filtered
                    if post.passes_tag_filter_for_user(subscriber):
                        return True
                else:

                    origin_post = post.get_origin_post()

                    if feed.feed_type == 'q_ask':
                        if origin_post.author == subscriber:
                            return True

                    elif feed.feed_type == 'q_ans':
                        #make sure that subscriber answered origin post
                        answers = origin_post.answers.exclude(deleted=True)
                        if subscriber in answers.get_author_list():
                            return True

                    elif feed.feed_type == 'q_sel':
                        #make sure that subscriber has selected this post
                        #individually
                        if subscriber in origin_post.followed_by.all():
                            return True
        return False

class EmailFeedSetting(models.Model):
    DELTA_TABLE = {
        'i':datetime.timedelta(-1),#instant emails are processed separately
        'd':datetime.timedelta(1),
        'w':datetime.timedelta(7),
        'n':datetime.timedelta(-1),
    }
    FEED_TYPES = (
                    ('q_all',_('Entire forum')),
                    ('q_ask',_('Questions that I asked')),
                    ('q_ans',_('Questions that I answered')),
                    ('q_sel',_('Individually selected questions')),
                    ('m_and_c',_('Mentions and comment responses')),
                    )
    UPDATE_FREQUENCY = (
                    ('i',_('Instantly')),
                    ('d',_('Daily')),
                    ('w',_('Weekly')),
                    ('n',_('No email')),
                   )


    subscriber = models.ForeignKey(User, related_name='notification_subscriptions')
    feed_type = models.CharField(max_length=16,choices=FEED_TYPES)
    frequency = models.CharField(
                                    max_length=8,
                                    choices=const.NOTIFICATION_DELIVERY_SCHEDULE_CHOICES,
                                    default='n',
                                )
    added_at = models.DateTimeField(auto_now_add=True)
    reported_at = models.DateTimeField(null=True)

    objects = EmailFeedSettingManager()

    #functions for rich comparison
    #PRECEDENCE = ('i','d','w','n')#the greater ones are first
    #def __eq__(self, other):
    #    return self.id == other.id

#    def __eq__(self, other):
#        return self.id != other.id

#    def __gt__(self, other):
#        return PRECEDENCE.index(self.frequency) < PRECEDENCE.index(other.frequency) 

#    def __lt__(self, other):
#        return PRECEDENCE.index(self.frequency) > PRECEDENCE.index(other.frequency) 

#    def __gte__(self, other):
#        if self.__eq__(other):
#            return True
#        else:
#            return self.__gt__(other)

#    def __lte__(self, other):
#        if self.__eq__(other):
#            return True
#        else:
#            return self.__lt__(other)

    def save(self,*args,**kwargs):
        type = self.feed_type
        subscriber = self.subscriber
        similar = self.__class__.objects.filter(
                                            feed_type=type,
                                            subscriber=subscriber
                                        ).exclude(pk=self.id)
        if len(similar) > 0:
            raise IntegrityError('email feed setting already exists')
        super(EmailFeedSetting,self).save(*args,**kwargs)

    def get_previous_report_cutoff_time(self):
        now = datetime.datetime.now()
        return now - self.DELTA_TABLE[self.frequency]

    def should_send_now(self):
        now = datetime.datetime.now()
        cutoff_time = self.get_previous_report_cutoff_time()
        if self.reported_at == None or self.reported_at <= cutoff_time:
            return True
        else:
            return False

    def mark_reported_now(self):
        self.reported_at = datetime.datetime.now()
        self.save()

    class Meta:
        app_label = 'forum'

from forum.utils.time import one_day_from_now

class ValidationHashManager(models.Manager):
    def _generate_md5_hash(self, user, type, hash_data, seed):
        return md5(
                    "%s%s%s%s"  % (
                                    seed, 
                                    "".join(map(str, hash_data)), 
                                    user.id, 
                                    type
                                )
                ).hexdigest()

    def create_new(self, user, type, hash_data=[], expiration=None):
        seed = ''.join(Random().sample(string.letters+string.digits, 12))
        hash = self._generate_md5_hash(user, type, hash_data, seed)

        obj = ValidationHash(hash_code=hash, seed=seed, user=user, type=type)

        if expiration is not None:
            obj.expiration = expiration

        try:
            obj.save()
        except:
            return None
            
        return obj

    def validate(self, hash, user, type, hash_data=[]):
        try:
            obj = self.get(hash_code=hash)
        except:
            return False

        if obj.type != type:
            return False

        if obj.user != user:
            return False

        valid = (obj.hash_code == self._generate_md5_hash(
                                            obj.user, 
                                            type, 
                                            hash_data, 
                                            obj.seed
                                        )
                )

        if valid:
            if obj.expiration < datetime.datetime.now():
                obj.delete()
                return False
            else:
                obj.delete()
                return True

        return False

class ValidationHash(models.Model):
    #todo: was 256 chars - is that important?
    #on mysql 255 is max for unique=True
    hash_code = models.CharField(max_length=255,unique=True)
    seed = models.CharField(max_length=12)
    expiration = models.DateTimeField(default=one_day_from_now)
    type = models.CharField(max_length=12)
    user = models.ForeignKey(User)

    objects = ValidationHashManager()

    class Meta:
        unique_together = ('user', 'type')
        app_label = 'forum'

    def __str__(self):
        return self.hash_code

#class AuthKeyUserAssociation(models.Model):
#    key = models.CharField(max_length=255,null=False,unique=True)
#    provider = models.CharField(max_length=64)#string 'yahoo', 'google', etc.
#    user = models.ForeignKey(User, related_name="auth_keys")
#    added_at = models.DateTimeField(default=datetime.datetime.now)
#
#    class Meta:
#        app_label = 'forum'
