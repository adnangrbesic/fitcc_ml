import pika
import json
import logging
import os

logger = logging.getLogger("scraper.publisher")

class RabbitMqPublisher:
    def __init__(self, host=None, queue='listing_scrape'):
        self.host = host or os.getenv('RABBITMQ_HOST', 'localhost')
        self.queue = queue
        self._connection = None
        self._channel = None

    def connect(self):
        import time
        attempts = 0
        while attempts < 5:
            try:
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    heartbeat=600,  # 10 minutes to survive LLM lag
                    blocked_connection_timeout=300
                )
                self._connection = pika.BlockingConnection(parameters)
                self._channel = self._connection.channel()
                self._channel.queue_declare(queue=self.queue, durable=True)
                logger.info(f"Connected to RabbitMQ at {self.host}, queue: {self.queue}")
                return
            except Exception as e:
                attempts += 1
                logger.error(f"Failed to connect to RabbitMQ (attempt {attempts}/5): {e}")
                time.sleep(5)

    def publish_listing(self, listing_data):
        if not self._channel:
            self.connect()
        
        if self._channel:
            try:
                self._channel.basic_publish(
                    exchange='',
                    routing_key=self.queue,
                    body=json.dumps(listing_data),
                    properties=pika.BasicProperties(delivery_mode=2)  # make message persistent
                )
                logger.info(f"Published listing to RabbitMQ: {listing_data.get('item_id')}")
            except Exception as e:
                logger.error(f"Failed to publish to RabbitMQ: {e}")
                self._channel = None # Reset for next attempt

    def close(self):
        if self._connection:
            self._connection.close()
